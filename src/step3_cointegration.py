"""
Étape 3 — Cointegration OLS + AR(1).

Construit le spread entre deux actifs I(1), valide son caractère
mean-reverting (test DF avec seuils MacKinnon), et vérifie la
stabilité structurelle du β sur 30 jours.

Toujours sur données 5min — pas de downsampling.

Inputs:
    - Deux DataFrames 5min (A et B) produits par step1
    - Symboles des deux actifs

Outputs:
    - Dict avec paramètres OLS/AR(1) sur 30j (meilleure direction),
      diagnostics 10j/60j, stabilité β, statut bloquant

Source de vérité : docs/recherche/modele_cointegration_v1_FINAL.docx — Section 6.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.contracts import MACKINNON_CV


# ---------------------------------------------------------------------------
# 1. Préparation des données de paire
# ---------------------------------------------------------------------------

def prepare_pair_data(df_a: pd.DataFrame, df_b: pd.DataFrame) -> pd.DataFrame:
    """Inner join + exclusion des barres flaggées + log-prix.

    Exclut les barres où rollover_discontinuity ou low_liquidity_day
    est True sur l'un ou l'autre actif.

    Input:  Deux DataFrames 5min (step1)
    Output: DataFrame avec log_a, log_b, session_id sur timestamps communs
    """
    common = df_a.index.intersection(df_b.index)

    pair = pd.DataFrame(index=common)
    pair["log_a"] = np.log(df_a.loc[common, "price"])
    pair["log_b"] = np.log(df_b.loc[common, "price"])
    pair["session_id"] = df_a.loc[common, "session_id"]

    # Exclure barres flaggées sur l'un ou l'autre actif
    exclude = pd.Series(False, index=common)
    for flag in ["rollover_discontinuity", "low_liquidity_day"]:
        if flag in df_a.columns:
            exclude = exclude | df_a.loc[common, flag]
        if flag in df_b.columns:
            exclude = exclude | df_b.loc[common, flag]

    n_excl = exclude.sum()
    if n_excl > 0:
        print(f"  barres exclues (rollover/low_liq): {n_excl}")

    return pair[~exclude].copy()


def select_pair_window(pair: pd.DataFrame,
                       n_sessions: int) -> pd.DataFrame | None:
    """Sélectionne les n dernières sessions de la paire.

    Input:  DataFrame paire, nombre de sessions
    Output: DataFrame filtré, ou None si pas assez de sessions
    """
    sessions = sorted(pair["session_id"].unique())
    if len(sessions) < n_sessions:
        return None
    selected = set(sessions[-n_sessions:])
    return pair[pair["session_id"].isin(selected)].copy()


# ---------------------------------------------------------------------------
# 2. Régression OLS
# ---------------------------------------------------------------------------

def run_ols_regression(log_dep: pd.Series,
                       log_indep: pd.Series) -> dict:
    """OLS : log_dep = α + β × log_indep + ε.

    Input:  Series log-prix dépendant et indépendant
    Output: dict avec alpha, beta, SE, R², résidus
    """
    X = sm.add_constant(log_indep.values)
    model = sm.OLS(log_dep.values, X).fit()

    return {
        "alpha": float(model.params[0]),
        "beta": float(model.params[1]),
        "se_alpha": float(model.bse[0]),
        "se_beta": float(model.bse[1]),
        "r_squared": float(model.rsquared),
        "resid_var": float(model.mse_resid),
    }


def compute_spread(log_a: pd.Series, log_b: pd.Series,
                   alpha: float, beta: float) -> pd.Series:
    """Spread canonique avec α (V1 §6.1).

    Spread_t = log(A)_t − α̂ − β̂ × log(B)_t

    Input:  log-prix A et B, paramètres OLS
    Output: Series du spread
    """
    return log_a - alpha - beta * log_b


# ---------------------------------------------------------------------------
# 3. Test AR(1) / Dickey-Fuller avec seuils MacKinnon
# ---------------------------------------------------------------------------

def run_ar1_df_test(spread: pd.Series) -> dict:
    """AR(1) sur le spread + statistique Dickey-Fuller.

    Spread_t = c + φ × Spread_{t-1} + η_t
    t_DF = (φ̂ − 1) / SE(φ̂)

    PROHIBITION #6 : utiliser MacKinnon, pas DF standard.

    Input:  Series du spread
    Output: dict avec φ, c, σ_η, t_DF, SE(φ), nobs
    """
    y = spread.iloc[1:].values
    X = sm.add_constant(spread.iloc[:-1].values)
    model = sm.OLS(y, X).fit()

    phi = float(model.params[1])
    se_phi = float(model.bse[1])
    t_df = (phi - 1.0) / se_phi

    return {
        "c": float(model.params[0]),
        "phi": phi,
        "se_phi": se_phi,
        "sigma_eta": float(np.sqrt(model.mse_resid)),
        "t_df": t_df,
        "nobs": int(model.nobs),
    }


def is_stationary_mackinnon(t_df: float, window_name: str,
                            level: str = "5%") -> bool:
    """Compare t_DF aux seuils MacKinnon pour résidus bivariés.

    Rejette H0 (unit root) si t_DF < valeur critique.

    Input:  t-stat DF, nom de fenêtre ("10d"/"30d"/"60d"), niveau
    Output: True si spread stationnaire (rejet H0)
    """
    cv = MACKINNON_CV[window_name][level]
    return t_df < cv


# ---------------------------------------------------------------------------
# 4. Analyse dans une direction
# ---------------------------------------------------------------------------

def run_direction(log_dep: pd.Series, log_indep: pd.Series,
                  window_name: str) -> dict:
    """OLS + AR(1) + MacKinnon dans une direction.

    Input:  log-prix dep/indep, nom de fenêtre
    Output: dict avec ols, ar1, spread, is_stationary
    """
    ols = run_ols_regression(log_dep, log_indep)
    spread = compute_spread(log_dep, log_indep, ols["alpha"], ols["beta"])
    ar1 = run_ar1_df_test(spread)
    stationary = is_stationary_mackinnon(ar1["t_df"], window_name)

    return {
        "ols": ols,
        "ar1": ar1,
        "is_stationary": stationary,
    }


def run_both_directions(pair: pd.DataFrame,
                        window_name: str) -> dict:
    """Teste les deux directions et retient la meilleure.

    Meilleure = t_DF le plus négatif (spread le plus stationnaire).
    Critère AR(1), pas R².

    Input:  DataFrame paire avec log_a/log_b, nom de fenêtre
    Output: dict avec résultats A→B et B→A, meilleure direction
    """
    dir_ab = run_direction(pair["log_a"], pair["log_b"], window_name)
    dir_ba = run_direction(pair["log_b"], pair["log_a"], window_name)

    # Meilleure direction = t_DF le plus négatif
    if dir_ab["ar1"]["t_df"] <= dir_ba["ar1"]["t_df"]:
        best = "A_B"
    else:
        best = "B_A"

    return {
        "A_B": dir_ab,
        "B_A": dir_ba,
        "best_direction": best,
    }


# ---------------------------------------------------------------------------
# 5. Stabilité structurelle (V1 §6.3 — sur 30j)
# ---------------------------------------------------------------------------

def compute_stability(pair: pd.DataFrame, direction: str,
                      alpha_full: float, beta_full: float,
                      n_sessions: int = 30) -> dict | None:
    """Stabilité β rolling et variance du spread sur 30j.

    Découpe en 3 blocs de 10j. Calcule CV(β) et Ratio_var.

    Input:  DataFrame paire (30j), direction retenue,
            paramètres OLS du full window
    Output: dict avec betas, CV, vars, ratio, statuts
    """
    sessions = sorted(pair["session_id"].unique())
    if len(sessions) < n_sessions:
        return None

    selected = sessions[-n_sessions:]
    block_size = n_sessions // 3

    blocks = [
        selected[:block_size],
        selected[block_size:2 * block_size],
        selected[2 * block_size:],
    ]

    # Déterminer dep/indep selon la direction
    dep_col = "log_a" if direction == "A_B" else "log_b"
    indep_col = "log_b" if direction == "A_B" else "log_a"

    betas: list[float] = []
    spread_vars: list[float] = []

    for block_sessions in blocks:
        block = pair[pair["session_id"].isin(block_sessions)]
        # β re-estimé par bloc
        ols_block = run_ols_regression(block[dep_col], block[indep_col])
        betas.append(ols_block["beta"])
        # Variance du spread avec paramètres du full window
        spread_block = compute_spread(
            block[dep_col], block[indep_col], alpha_full, beta_full
        )
        spread_vars.append(float(spread_block.var()))

    # CV(β) = std / |mean|
    cv_beta = float(np.std(betas, ddof=0) / abs(np.mean(betas)))

    # Ratio_var = max / min
    var_ratio = max(spread_vars) / min(spread_vars) if min(spread_vars) > 0 else np.inf

    # Statuts (V1 §6.3)
    if cv_beta < 0.10:
        beta_status = "green"
    elif cv_beta < 0.20:
        beta_status = "orange"
    else:
        beta_status = "red"

    if var_ratio < 1.5:
        var_status = "green"
    elif var_ratio < 2.0:
        var_status = "orange"
    else:
        var_status = "red"

    return {
        "betas": betas,
        "cv_beta": cv_beta,
        "beta_status": beta_status,
        "spread_vars": spread_vars,
        "var_ratio": float(var_ratio),
        "var_status": var_status,
    }


# ---------------------------------------------------------------------------
# 6. Pipeline complet étape 3
# ---------------------------------------------------------------------------

def run_step3(df_a: pd.DataFrame, df_b: pd.DataFrame,
              symbol_a: str, symbol_b: str) -> dict:
    """Pipeline complet étape 3 : cointegration OLS + AR(1).

    Input:  Deux DataFrames 5min (step1), symboles
    Output: dict avec paramètres OLS/AR(1), stabilité, bloquant

    Structure de sortie:
        {
            "symbol_a", "symbol_b",
            "direction": "A_B" | "B_A",
            "dep", "indep",
            "beta_ols", "alpha_ols", "phi", "c_ar1", "sigma_eta",
            "se_alpha", "se_beta", "mu_b",
            "t_df_30d", "mackinnon_cv_30d", "is_stationary_30d",
            "stability": {...},
            "windows": {"10d": {...}, "30d": {...}, "60d": {...}},
            "is_blocking": bool,
        }
    """
    print(f"=== STEP 3 — {symbol_a}/{symbol_b} ===")

    # 1. Préparer les données de paire
    pair = prepare_pair_data(df_a, df_b)
    n_sessions = len(pair["session_id"].unique())
    print(f"  barres communes: {len(pair)}, sessions: {n_sessions}")

    # 2. Tester sur 3 fenêtres
    windows: dict = {}
    any_stationary = False

    for wname, n_sess in [("10d", 10), ("30d", 30), ("60d", 60)]:
        window = select_pair_window(pair, n_sess)
        if window is None:
            print(f"  {wname}: pas assez de sessions")
            windows[wname] = None
            continue

        n_bars = len(window)
        result = run_both_directions(window, wname)

        best = result["best_direction"]
        best_data = result[best]
        t_df = best_data["ar1"]["t_df"]
        cv = MACKINNON_CV[wname]["5%"]
        stat = best_data["is_stationary"]

        if stat:
            any_stationary = True

        # Vérifier si stationnaire dans l'autre direction aussi
        other = "B_A" if best == "A_B" else "A_B"
        other_stat = result[other]["is_stationary"]
        if other_stat:
            any_stationary = True

        windows[wname] = result

        print(f"  {wname}: N={n_bars}, best={best}, "
              f"t_DF={t_df:.3f} (CV={cv:.2f}) "
              f"-> {'STATIONNAIRE' if stat else 'non-stat'}"
              f" | autre dir: {'stat' if other_stat else 'non-stat'}")

    # 3. Direction retenue = meilleure sur 30j
    if windows.get("30d") is None:
        print("  ERREUR: pas assez de sessions pour 30j")
        return {"is_blocking": True, "error": "insufficient_sessions"}

    best_dir_30d = windows["30d"]["best_direction"]
    best_30d = windows["30d"][best_dir_30d]

    # Déterminer dep/indep
    if best_dir_30d == "A_B":
        dep, indep = symbol_a, symbol_b
    else:
        dep, indep = symbol_b, symbol_a

    # 4. Extraire les paramètres 30j
    ols = best_30d["ols"]
    ar1 = best_30d["ar1"]

    # μ_B = mean(log(indep)) sur 30j
    window_30d = select_pair_window(pair, 30)
    indep_col = "log_b" if best_dir_30d == "A_B" else "log_a"
    mu_b = float(window_30d[indep_col].mean())

    # 5. Stabilité structurelle sur 30j
    stability = compute_stability(
        pair, best_dir_30d,
        alpha_full=ols["alpha"], beta_full=ols["beta"],
        n_sessions=30,
    )

    # 6. Condition bloquante
    # Bloquant si non-stationnaire sur TOUTES fenêtres dans les DEUX directions
    is_blocking = not any_stationary

    # 7. Résumé
    print()
    print(f"  === VERDICT {symbol_a}/{symbol_b} ===")
    print(f"  Direction retenue: {best_dir_30d} (dep={dep}, indep={indep})")
    print(f"  beta_OLS={ols['beta']:.6f}, alpha_OLS={ols['alpha']:.6f}")
    print(f"  phi={ar1['phi']:.6f}, sigma_eta={ar1['sigma_eta']:.6f}")
    print(f"  t_DF(30d)={ar1['t_df']:.3f}, "
          f"CV MacKinnon={MACKINNON_CV['30d']['5%']:.2f}")
    print(f"  Stationnaire 30d: {best_30d['is_stationary']}")
    if stability:
        print(f"  CV(beta)={stability['cv_beta']:.4f} "
              f"[{stability['beta_status']}]")
        print(f"  Ratio_var={stability['var_ratio']:.3f} "
              f"[{stability['var_status']}]")
    if is_blocking:
        print(f"  BLOQUANT: non-stationnaire sur toutes les fenetres")
    print()

    return {
        "symbol_a": symbol_a,
        "symbol_b": symbol_b,
        "direction": best_dir_30d,
        "dep": dep,
        "indep": indep,
        # Paramètres 30j meilleure direction
        "beta_ols": ols["beta"],
        "alpha_ols": ols["alpha"],
        "phi": ar1["phi"],
        "c_ar1": ar1["c"],
        "sigma_eta": ar1["sigma_eta"],
        "se_alpha": ols["se_alpha"],
        "se_beta": ols["se_beta"],
        "mu_b": mu_b,
        "r_squared": ols["r_squared"],
        "resid_var": ols["resid_var"],
        # Test MacKinnon 30j
        "t_df_30d": ar1["t_df"],
        "mackinnon_cv_30d": MACKINNON_CV["30d"]["5%"],
        "is_stationary_30d": best_30d["is_stationary"],
        # Stabilité 30j
        "stability": stability,
        # Toutes les fenêtres (diagnostics)
        "windows": windows,
        # Bloquant
        "is_blocking": is_blocking,
    }


# ---------------------------------------------------------------------------
# Main — test isolé
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from src.step1_data import run_step1

    data_dir = _PROJECT_ROOT / "data" / "raw"

    gc_files = list(data_dir.glob("GC*"))
    si_files = list(data_dir.glob("SI*"))

    if gc_files and si_files:
        df_gc = run_step1(gc_files[0], "GC")
        df_si = run_step1(si_files[0], "SI")
        result = run_step3(df_gc, df_si, "GC", "SI")
        print(f"Blocking: {result['is_blocking']}")
        print(f"Direction: {result['direction']}")
        print(f"beta={result['beta_ols']:.6f}, phi={result['phi']:.6f}")
