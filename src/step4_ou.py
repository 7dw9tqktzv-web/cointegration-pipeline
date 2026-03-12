"""
Etape 4 -- Ornstein-Uhlenbeck : qualification du spread.

Convertit les parametres AR(1) (step3) en parametres OU continus,
calcule le half-life empirique, et valide la coherence du modele.

Convention universelle : dt = 1 barre de 5min (pas-a-pas).

Inputs:
    - Resultats step3 (phi, c, sigma_eta, alpha_ols, beta_ols, ...)
    - DataFrames 5min des deux actifs (pour recalculer le spread)

Outputs:
    - Dict avec kappa, theta_ou, sigma_eq, HL empirique/modele,
      assertions de sante, statut bloquant

Source de verite : docs/recherche/modele_cointegration_v1_FINAL.docx -- Section 7.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 1. Conversion AR(1) -> parametres OU (V1 S7.1)
# ---------------------------------------------------------------------------

def convert_ar1_to_ou(phi: float, c: float, sigma_eta: float,
                      dt: float = 1.0) -> dict:
    """Convertit les parametres AR(1) en parametres OU continus.

    Formules de Paolucci (2026) :
        kappa       = -ln(phi) / dt
        theta_ou    = c / (1 - phi)
        sigma_eq    = sigma_eta / sqrt(1 - phi^2)
        sigma_diff  = sigma_eta * sqrt(-2*ln(phi) / (1 - phi^2))

    Input:  phi, c, sigma_eta issus de run_ar1_df_test (step3), dt
    Output: dict avec kappa, theta_ou, sigma_eq, sigma_diffusion, q_ou
    """
    assert 0 < phi < 1, f"phi={phi} hors ]0,1[ -- conversion OU impossible"

    kappa = -np.log(phi) / dt
    theta_ou = c / (1.0 - phi)
    sigma_eq = sigma_eta / np.sqrt(1.0 - phi ** 2)
    sigma_diffusion = sigma_eta * np.sqrt(-2.0 * np.log(phi) / (1.0 - phi ** 2))

    # Q_OU = variance conditionnelle du spread par barre (usage interne)
    q_ou = (sigma_diffusion ** 2 / (2.0 * kappa)) * (1.0 - np.exp(-2.0 * kappa * dt))

    return {
        "kappa": float(kappa),
        "theta_ou": float(theta_ou),
        "sigma_eq": float(sigma_eq),
        "sigma_diffusion": float(sigma_diffusion),
        "q_ou": float(q_ou),
    }


# ---------------------------------------------------------------------------
# 2. Half-life modele et empirique (V1 S7.3 + audit)
# ---------------------------------------------------------------------------

def compute_hl_model(kappa: float) -> float:
    """Half-life modele en barres 5min.

    HL_modele = ln(2) / kappa

    Input:  kappa (vitesse de retour)
    Output: half-life en barres
    """
    return np.log(2) / kappa


def compute_hl_empirical(spread: pd.Series, sigma_eq: float,
                         theta_ou: float) -> dict:
    """Half-life empirique = mediane des temps de retour.

    Mesure les traversees |Z| > 2 -> |Z| < 0.5.
    Audit : minimum 5 traversees, sinon None + fallback HL_modele.

    Input:  spread series, sigma_eq, theta_ou
    Output: dict avec crossing_times, hl_empirical, n_crossings
    """
    z = (spread.values - theta_ou) / sigma_eq

    crossing_times: list[int] = []
    in_excursion = False
    entry_bar = 0

    for i in range(len(z)):
        if not in_excursion and abs(z[i]) > 2.0:
            in_excursion = True
            entry_bar = i
        elif in_excursion and abs(z[i]) < 0.5:
            crossing_times.append(i - entry_bar)
            in_excursion = False

    n_crossings = len(crossing_times)

    if n_crossings < 5:
        hl_empirical = None
    else:
        hl_empirical = float(np.median(crossing_times))

    return {
        "crossing_times": crossing_times,
        "hl_empirical": hl_empirical,
        "n_crossings": n_crossings,
    }


def evaluate_hl_ratio(hl_empirical: float | None,
                      hl_model: float) -> dict:
    """Evalue le ratio HL_empirique / HL_modele.

    Seuils V1 S7.3 :
        green  : 0.8 - 1.5
        orange : 1.5 - 2.0 OU < 0.8 (sauf < 0.33)
        red    : > 2.0 OU < 0.33
    BLOQUANT : ratio > 3.0 uniquement

    Si hl_empirical is None (< 5 traversees, audit) :
        fallback sur HL_modele, statut orange

    Input:  hl_empirical (ou None), hl_model
    Output: dict avec ratio, hl_operational, status, is_blocking
    """
    if hl_empirical is None:
        return {
            "ratio": None,
            "hl_operational": hl_model,
            "hl_status": "orange",
            "hl_source": "model_fallback",
            "is_blocking": False,
        }

    ratio = hl_empirical / hl_model

    if ratio > 3.0:
        status = "red"
        is_blocking = True
    elif ratio < 0.33:
        status = "red"
        is_blocking = False
    elif ratio > 2.0:
        status = "red"
        is_blocking = False
    elif ratio > 1.5:
        status = "orange"
        is_blocking = False
    elif ratio < 0.8:
        status = "orange"
        is_blocking = False
    else:
        status = "green"
        is_blocking = False

    return {
        "ratio": float(ratio),
        "hl_operational": hl_empirical,
        "hl_status": status,
        "hl_source": "empirical",
        "is_blocking": is_blocking,
    }


# ---------------------------------------------------------------------------
# 3. Assertions de sante (V1 S7.4)
# ---------------------------------------------------------------------------

def check_theta_ou(theta_ou: float, sigma_eq: float) -> dict:
    """Verifie |theta_OU| < 0.01 * sigma_eq (coherence OLS).

    Input:  theta_ou, sigma_eq
    Output: dict avec ok, ratio, message
    """
    ratio = abs(theta_ou) / sigma_eq if sigma_eq > 0 else np.inf
    ok = ratio < 0.01

    return {
        "ok": ok,
        "ratio": float(ratio),
        "threshold": 0.01,
    }


def check_zscore_crosscheck(spread: pd.Series, theta_ou: float,
                            sigma_eq: float) -> dict:
    """Cross-check sigma_eq vs std(spread) via Z-scores.

    z_modele    = (Spread - theta_OU) / sigma_eq
    z_empirique = (Spread - mean(Spread)) / std(Spread)
    Delta_z     = |z_modele - z_empirique|

    Seuils V1 S7.4 : median(Dz) < 0.02 AND percentile_99(Dz) < 0.15

    Input:  spread series, theta_ou, sigma_eq
    Output: dict avec median_dz, p99_dz, ok
    """
    spread_vals = spread.values
    z_model = (spread_vals - theta_ou) / sigma_eq
    z_empirical = (spread_vals - np.mean(spread_vals)) / np.std(spread_vals, ddof=1)

    dz = np.abs(z_model - z_empirical)

    median_dz = float(np.median(dz))
    p99_dz = float(np.percentile(dz, 99))

    ok = (median_dz < 0.02) and (p99_dz < 0.15)

    return {
        "median_dz": median_dz,
        "p99_dz": p99_dz,
        "ok": ok,
    }


def run_assertions(phi: float, ou_params: dict, spread: pd.Series) -> dict:
    """Toutes les assertions de sante V1 S7.4.

    Input:  phi (AR1), ou_params (convert_ar1_to_ou), spread
    Output: dict avec chaque assertion et is_blocking global
    """
    kappa = ou_params["kappa"]
    theta_ou = ou_params["theta_ou"]
    sigma_eq = ou_params["sigma_eq"]

    # Bloquants
    phi_ok = 0 < phi < 1
    kappa_ok = kappa > 0
    sigma_eq_ok = sigma_eq > 0 and np.isfinite(sigma_eq)

    # Alertes
    theta_check = check_theta_ou(theta_ou, sigma_eq)
    zscore_check = check_zscore_crosscheck(spread, theta_ou, sigma_eq)

    is_blocking = not (phi_ok and kappa_ok and sigma_eq_ok)

    return {
        "phi_in_range": phi_ok,
        "kappa_positive": kappa_ok,
        "sigma_eq_valid": sigma_eq_ok,
        "theta_ou_check": theta_check,
        "zscore_crosscheck": zscore_check,
        "is_blocking": is_blocking,
    }


# ---------------------------------------------------------------------------
# 4. Pipeline complet etape 4
# ---------------------------------------------------------------------------

def run_step4(step3_result: dict,
              df_a: pd.DataFrame, df_b: pd.DataFrame) -> dict:
    """Pipeline complet etape 4 : qualification OU du spread.

    Input:
        - step3_result: dict produit par run_step3
        - df_a, df_b: DataFrames 5min (step1)
    Output:
        dict avec parametres OU, half-life, assertions, bloquant

    Structure de sortie:
        {
            "kappa", "theta_ou", "sigma_eq",
            "sigma_diffusion", "q_ou",
            "hl_model", "hl_empirical", "hl_operational",
            "hl_ratio", "hl_status", "hl_source",
            "assertions": {...},
            "is_blocking": bool,
            # Pass-through de step3 pour step5
            "alpha_ols", "beta_ols",
            "se_alpha", "se_beta",
            "resid_var", "direction",
            "symbol_a", "symbol_b",
        }
    """
    print(f"=== STEP 4 -- {step3_result['symbol_a']}/{step3_result['symbol_b']} ===")

    phi = step3_result["phi"]
    c = step3_result["c_ar1"]
    sigma_eta = step3_result["sigma_eta"]

    # 1. Verifier phi in ]0, 1[
    if not (0 < phi < 1):
        print(f"  BLOQUANT: phi={phi:.6f} hors ]0,1[")
        return {
            "is_blocking": True,
            "error": f"phi={phi} hors ]0,1[",
        }

    # 2. Conversion AR(1) -> OU
    ou = convert_ar1_to_ou(phi, c, sigma_eta)
    print(f"  kappa={ou['kappa']:.6f}, theta_OU={ou['theta_ou']:.6f}")
    print(f"  sigma_eq={ou['sigma_eq']:.6f}, "
          f"sigma_diff={ou['sigma_diffusion']:.6f}")
    print(f"  Q_OU={ou['q_ou']:.2e} (interne uniquement)")

    # 3. Reconstruire le spread sur 30j
    from src.step3_cointegration import (
        prepare_pair_data, select_pair_window, compute_spread,
    )

    pair = prepare_pair_data(df_a, df_b)
    window_30d = select_pair_window(pair, 30)

    if window_30d is None:
        print("  ERREUR: pas assez de sessions pour 30j")
        return {"is_blocking": True, "error": "insufficient_sessions"}

    direction = step3_result["direction"]
    dep_col = "log_a" if direction == "A_B" else "log_b"
    indep_col = "log_b" if direction == "A_B" else "log_a"

    spread = compute_spread(
        window_30d[dep_col], window_30d[indep_col],
        step3_result["alpha_ols"], step3_result["beta_ols"],
    )
    print(f"  spread: N={len(spread)}, "
          f"mean={spread.mean():.6f}, std={spread.std():.6f}")

    # 4. Half-life
    hl_model = compute_hl_model(ou["kappa"])
    hl_data = compute_hl_empirical(spread, ou["sigma_eq"], ou["theta_ou"])
    hl_eval = evaluate_hl_ratio(hl_data["hl_empirical"], hl_model)

    print(f"  HL_modele={hl_model:.1f} barres ({hl_model * 5:.0f} min)")
    print(f"  HL_empirique={hl_data['hl_empirical']} "
          f"({hl_data['n_crossings']} traversees)")
    if hl_eval["ratio"] is not None:
        print(f"  Ratio HL={hl_eval['ratio']:.2f} [{hl_eval['hl_status']}]")
    else:
        print(f"  Ratio HL=N/A (< 5 traversees, fallback modele) "
              f"[{hl_eval['hl_status']}]")
    print(f"  HL_operationnel={hl_eval['hl_operational']:.1f} barres "
          f"({hl_eval['hl_operational'] * 5:.0f} min) "
          f"[source: {hl_eval['hl_source']}]")

    # 5. Assertions de sante
    assertions = run_assertions(phi, ou, spread)

    print(f"  theta_OU check: "
          f"|theta|/sigma_eq={assertions['theta_ou_check']['ratio']:.4f} "
          f"{'OK' if assertions['theta_ou_check']['ok'] else 'ALERTE'}")
    print(f"  Z cross-check: "
          f"median(dz)={assertions['zscore_crosscheck']['median_dz']:.4f}, "
          f"p99(dz)={assertions['zscore_crosscheck']['p99_dz']:.4f} "
          f"{'OK' if assertions['zscore_crosscheck']['ok'] else 'ALERTE'}")

    # 6. Bloquant global
    is_blocking = assertions["is_blocking"] or hl_eval["is_blocking"]

    # 7. Resume
    print()
    print(f"  === VERDICT ===")
    print(f"  sigma_eq={ou['sigma_eq']:.6f} (Z-score denominator)")
    print(f"  HL operationnel={hl_eval['hl_operational']:.1f} barres")
    if is_blocking:
        reasons = []
        if assertions["is_blocking"]:
            reasons.append("assertion OU")
        if hl_eval["is_blocking"]:
            reasons.append(f"ratio HL={hl_eval['ratio']:.2f} > 3.0")
        print(f"  BLOQUANT: {', '.join(reasons)}")
    else:
        print(f"  NON BLOQUANT")
    print()

    return {
        # Parametres OU
        "kappa": ou["kappa"],
        "theta_ou": ou["theta_ou"],
        "sigma_eq": ou["sigma_eq"],
        "sigma_diffusion": ou["sigma_diffusion"],
        "q_ou": ou["q_ou"],
        # Half-life
        "hl_model": float(hl_model),
        "hl_empirical": hl_data["hl_empirical"],
        "hl_operational": hl_eval["hl_operational"],
        "hl_ratio": hl_eval["ratio"],
        "hl_status": hl_eval["hl_status"],
        "hl_source": hl_eval["hl_source"],
        "n_crossings": hl_data["n_crossings"],
        # Assertions
        "assertions": assertions,
        # Bloquant
        "is_blocking": is_blocking,
        # Pass-through step3 -> step5
        "alpha_ols": step3_result["alpha_ols"],
        "beta_ols": step3_result["beta_ols"],
        "se_alpha": step3_result["se_alpha"],
        "se_beta": step3_result["se_beta"],
        "resid_var": step3_result["resid_var"],
        "mu_b": step3_result["mu_b"],
        "direction": step3_result["direction"],
        "symbol_a": step3_result["symbol_a"],
        "symbol_b": step3_result["symbol_b"],
        # Pass-through AR(1) bruts pour debug/logging backtester
        "phi": step3_result["phi"],
        "c_ar1": step3_result["c_ar1"],
        "sigma_eta": step3_result["sigma_eta"],
    }


# ---------------------------------------------------------------------------
# Main -- test isole
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from src.step1_data import run_step1
    from src.step3_cointegration import run_step3

    data_dir = _PROJECT_ROOT / "data" / "raw"

    gc_files = list(data_dir.glob("GC*"))
    si_files = list(data_dir.glob("SI*"))

    if gc_files and si_files:
        df_gc = run_step1(gc_files[0], "GC")
        df_si = run_step1(si_files[0], "SI")
        s3 = run_step3(df_gc, df_si, "GC", "SI")

        if not s3.get("is_blocking", False):
            result = run_step4(s3, df_gc, df_si)
            print(f"Blocking: {result['is_blocking']}")
        else:
            print("Step3 bloquant -- step4 non execute")
