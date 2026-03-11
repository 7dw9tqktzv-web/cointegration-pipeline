"""
Étape 2 — Tests de Stationnarité (ADF + KPSS).

Valide que chaque actif est I(1) — non-stationnaire en niveau,
stationnaire en différence — condition préalable à la cointegration.

Downsampling session-aware pour contrer le biais Grand N (§5.1).
Multi-scale validation sur 3 fréquences par fenêtre (§5.2).
Correction Benjamini-Hochberg pour tests multiples.

Inputs:
    - DataFrame 5min produit par step1 (un actif à la fois)
    - Symbole de l'actif

Outputs:
    - Dict avec résultats ADF/KPSS par fenêtre/fréquence,
      verdict I(1) multi-scale, statut bloquant

Source de vérité : docs/recherche/modele_cointegration_v1_FINAL.docx — Section 5.
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, kpss
from statsmodels.stats.multitest import multipletests

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Configuration multi-scale par fenêtre (V1 §5.1–5.2)
# 3 fréquences par fenêtre : [haute, primaire, basse]
# "Plus basse" = plus grand intervalle = moins d'observations
#
# 10j: 2640 barres → freq primaire 15min (~880 obs)
# 30j: 7920 barres → freq primaire 30min (~1320 obs)
# 60j: 15840 barres → freq primaire 60min (~1320 obs)
# ---------------------------------------------------------------------------

WINDOW_CONFIG: dict[str, dict] = {
    "10d": {"sessions": 10, "freqs_min": [10, 15, 30]},
    "30d": {"sessions": 30, "freqs_min": [15, 30, 60]},
    "60d": {"sessions": 60, "freqs_min": [30, 60, 120]},
}

ALPHA = 0.05  # seuil de significativité
MIN_OBS = 50  # minimum d'observations pour un test valide


# ---------------------------------------------------------------------------
# 1. Sélection de fenêtre — sessions propres
# ---------------------------------------------------------------------------

def get_clean_sessions(df: pd.DataFrame) -> list[str]:
    """Retourne les session_ids propres (sans low_liq ni rollover).

    Exclut les sessions ayant au moins une barre flaggée
    low_liquidity_day ou rollover_discontinuity.

    Input:  DataFrame 5min avec flags
    Output: Liste triée de session_ids propres
    """
    exclude: set[str] = set()
    for flag in ["low_liquidity_day", "rollover_discontinuity"]:
        if flag in df.columns:
            bad = df[df[flag]]["session_id"].unique()
            exclude.update(bad)
    all_sessions = sorted(df["session_id"].unique())
    return [s for s in all_sessions if s not in exclude]


def select_window(df: pd.DataFrame, n_sessions: int) -> pd.DataFrame | None:
    """Sélectionne les n dernières sessions propres.

    Input:  DataFrame 5min, nombre de sessions voulues
    Output: DataFrame filtré, ou None si pas assez de sessions
    """
    clean = get_clean_sessions(df)
    if len(clean) < n_sessions:
        return None
    selected = set(clean[-n_sessions:])
    return df[df["session_id"].isin(selected)].copy()


# ---------------------------------------------------------------------------
# 2. Downsampling session-aware (V1 §5.1)
# ---------------------------------------------------------------------------

def downsample_session_aware(df: pd.DataFrame, freq_min: int) -> pd.Series:
    """Downsample le log-prix à la fréquence cible, session-aware.

    groupby('session_id') OBLIGATOIRE avant resample.
    Utilise 'last' pour le prix (= close de la barre downsampleée).

    Input:  DataFrame 5min avec colonne 'price', fréquence en minutes
    Output: Series de log-prix downsampleé (sans NaN)
    """
    if freq_min <= 5:
        return np.log(df["price"]).dropna()

    freq_str = f"{freq_min}min"
    groups = []
    for _sid, group in df.groupby("session_id"):
        lp = np.log(group["price"])
        resampled = lp.resample(freq_str).last().dropna()
        groups.append(resampled)

    if not groups:
        return pd.Series(dtype=float)

    return pd.concat(groups).sort_index()


# ---------------------------------------------------------------------------
# 3. Tests statistiques
# ---------------------------------------------------------------------------

def run_adf(series: pd.Series) -> dict:
    """Exécute le test ADF (Augmented Dickey-Fuller).

    H0 : unit root (non-stationnaire).
    Rejet H0 (p < α) → stationnaire → NON I(1) en niveau.
    Non-rejet (p > α) → compatible I(1).

    Input:  Series numérique sans NaN
    Output: dict avec stat, pvalue, nlags, nobs
    """
    result = adfuller(series.values, regression="c", autolag="AIC")
    return {
        "stat": result[0],
        "pvalue": result[1],
        "nlags": result[2],
        "nobs": result[3],
    }


def run_kpss(series: pd.Series) -> dict:
    """Exécute le test KPSS.

    H0 : stationnaire (autour d'une constante).
    Rejet H0 (p < α) → non-stationnaire → compatible I(1).
    Non-rejet (p > α) → stationnaire → NON I(1).

    Input:  Series numérique sans NaN
    Output: dict avec stat, pvalue, nlags
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # KPSS p-value interpolation warnings
        result = kpss(series.values, regression="c", nlags="auto")
    return {
        "stat": result[0],
        "pvalue": result[1],
        "nlags": result[2],
    }


def classify_stationarity(adf_pval: float, kpss_pval: float,
                           alpha: float = ALPHA) -> str:
    """Classifie selon la matrice ADF x KPSS (Table 5 du V1).

    Input:  p-values ADF et KPSS (éventuellement corrigées BH)
    Output: "I(1)" | "I(0)" | "inconsistent" | "ambiguous"
    """
    adf_reject = adf_pval < alpha
    kpss_reject = kpss_pval < alpha

    if not adf_reject and kpss_reject:
        return "I(1)"          # non-stationnaire confirmé
    elif adf_reject and not kpss_reject:
        return "I(0)"          # stationnaire → bloquant
    elif adf_reject and kpss_reject:
        return "inconsistent"  # les deux rejettent → observable
    else:
        return "ambiguous"     # aucun ne rejette → tester plus


# ---------------------------------------------------------------------------
# 4. Correction Benjamini-Hochberg
# ---------------------------------------------------------------------------

def apply_bh_correction(windows: dict) -> dict:
    """Applique Benjamini-Hochberg sur l'ensemble des p-values.

    Collecte tous les p-values ADF et KPSS de toutes les fenêtres/fréquences,
    applique BH, met à jour les résultats avec pvalue_adj et recalcule verdicts.

    Input:  dict des résultats par fenêtre (sortie de run_window_multiscale)
    Output: même dict avec pvalue_adj et verdicts recalculés
    """
    pvals: list[float] = []
    coords: list[tuple[str, int, str]] = []

    for wname, wdata in windows.items():
        if wdata is None:
            continue
        for freq, fdata in wdata["freqs"].items():
            pvals.append(fdata["adf"]["pvalue"])
            coords.append((wname, freq, "adf"))
            pvals.append(fdata["kpss"]["pvalue"])
            coords.append((wname, freq, "kpss"))

    if not pvals:
        return windows

    # BH correction
    _rejected, pvals_adj, _alphac_sidak, _alphac_bonf = multipletests(
        pvals, alpha=ALPHA, method="fdr_bh"
    )

    # Stocker p-values ajustées
    for i, (wname, freq, test_name) in enumerate(coords):
        windows[wname]["freqs"][freq][test_name]["pvalue_adj"] = pvals_adj[i]

    # Recalculer verdicts avec p-values ajustées
    for wname, wdata in windows.items():
        if wdata is None:
            continue
        for freq, fdata in wdata["freqs"].items():
            adf_padj = fdata["adf"]["pvalue_adj"]
            kpss_padj = fdata["kpss"]["pvalue_adj"]
            fdata["verdict_adj"] = classify_stationarity(adf_padj, kpss_padj)

    return windows


# ---------------------------------------------------------------------------
# 5. Multi-scale par fenêtre
# ---------------------------------------------------------------------------

def evaluate_multiscale(wdata: dict) -> dict:
    """Évalue le verdict multi-scale d'une fenêtre après BH.

    I(1) validé si confirmé sur >= 2 fréquences dont la plus basse.

    Input:  dict d'une fenêtre avec freqs et verdicts
    Output: même dict enrichi de i1_count, lowest_confirms_i1, i1_confirmed
    """
    freqs = wdata["freqs"]
    if not freqs:
        wdata.update({"i1_count": 0, "lowest_freq": None,
                       "lowest_confirms_i1": False, "i1_confirmed": False})
        return wdata

    # Plus basse fréquence = plus grand intervalle en minutes
    lowest_freq = max(freqs.keys())

    # Compter les fréquences qui confirment I(1) (après BH)
    verdict_key = "verdict_adj" if "verdict_adj" in next(iter(freqs.values())) else "verdict"
    i1_freqs = [f for f, d in freqs.items() if d[verdict_key] == "I(1)"]

    wdata["i1_count"] = len(i1_freqs)
    wdata["lowest_freq"] = lowest_freq
    wdata["lowest_confirms_i1"] = lowest_freq in i1_freqs
    wdata["i1_confirmed"] = (len(i1_freqs) >= 2) and wdata["lowest_confirms_i1"]

    return wdata


def run_window_multiscale(df: pd.DataFrame, window_name: str,
                          n_sessions: int, freqs: list[int]) -> dict | None:
    """Exécute les tests multi-scale ADF+KPSS sur une fenêtre.

    Input:  DataFrame 5min, nom/config de la fenêtre
    Output: dict avec résultats par fréquence, ou None si pas assez de sessions
    """
    window_df = select_window(df, n_sessions)
    if window_df is None:
        print(f"  {window_name}: pas assez de sessions propres")
        return None

    n_bars = len(window_df)
    result: dict = {"freqs": {}, "n_sessions": n_sessions, "n_bars_5min": n_bars}

    for freq in freqs:
        series = downsample_session_aware(window_df, freq)
        n_obs = len(series)

        if n_obs < MIN_OBS:
            print(f"  {window_name}/{freq}min: {n_obs} obs < {MIN_OBS}, skip")
            continue

        adf = run_adf(series)
        kpss_res = run_kpss(series)
        verdict = classify_stationarity(adf["pvalue"], kpss_res["pvalue"])

        result["freqs"][freq] = {
            "adf": adf,
            "kpss": kpss_res,
            "verdict": verdict,
            "n_obs": n_obs,
        }

        print(f"  {window_name}/{freq}min: N={n_obs:>5}, "
              f"ADF={adf['stat']:>7.3f} (p={adf['pvalue']:.4f}), "
              f"KPSS={kpss_res['stat']:.4f} (p={kpss_res['pvalue']:.4f}) "
              f"-> {verdict}")

    return result


# ---------------------------------------------------------------------------
# 6. Pipeline complet étape 2
# ---------------------------------------------------------------------------

def run_step2(df: pd.DataFrame, symbol: str) -> dict:
    """Pipeline complet étape 2 : tests de stationnarité multi-scale.

    Input:  DataFrame 5min produit par step1, symbole de l'actif
    Output: dict avec résultats par fenêtre, verdict I(1), statut bloquant

    Structure de sortie:
        {
            "symbol": str,
            "n_clean_sessions": int,
            "windows": {"10d": {...}, "30d": {...}, "60d": {...}},
            "is_I1": bool,
            "is_blocking": bool,
        }
    """
    print(f"=== STEP 2 — {symbol} ===")

    clean = get_clean_sessions(df)
    print(f"  sessions propres: {len(clean)}/{df['session_id'].nunique()}")

    # Exécuter chaque fenêtre
    windows: dict = {}
    for wname, cfg in WINDOW_CONFIG.items():
        print(f"  --- {wname} ({cfg['sessions']} sessions) ---")
        result = run_window_multiscale(
            df, wname, cfg["sessions"], cfg["freqs_min"]
        )
        windows[wname] = result

    # Correction Benjamini-Hochberg sur l'ensemble des p-values
    windows = apply_bh_correction(windows)

    # Évaluer multi-scale par fenêtre (après BH)
    for wname, wdata in windows.items():
        if wdata is not None:
            evaluate_multiscale(wdata)

    # Verdict global
    # I(1) si confirmé sur au moins une fenêtre majeure (30j ou 60j)
    i1_30d = windows.get("30d") is not None and windows["30d"].get("i1_confirmed", False)
    i1_60d = windows.get("60d") is not None and windows["60d"].get("i1_confirmed", False)
    is_i1 = i1_30d or i1_60d

    # Condition bloquante (V1 §5.2) :
    # non-I(1) sur 30j ET 60j, confirmé sur 2+ fréquences
    non_i1_30d = (windows.get("30d") is not None
                  and not windows["30d"].get("i1_confirmed", False))
    non_i1_60d = (windows.get("60d") is not None
                  and not windows["60d"].get("i1_confirmed", False))
    is_blocking = non_i1_30d and non_i1_60d

    # Résumé
    print()
    print(f"  === VERDICT {symbol} (apres BH) ===")
    for wn in ["10d", "30d", "60d"]:
        w = windows.get(wn)
        if w is None:
            print(f"  {wn}: N/A (pas assez de sessions)")
        else:
            status = "I(1)" if w.get("i1_confirmed") else "NON I(1)"
            print(f"  {wn}: {status} "
                  f"({w['i1_count']}/{len(w['freqs'])} freqs, "
                  f"lowest={'OK' if w.get('lowest_confirms_i1') else 'FAIL'})")

    print(f"  I(1) global: {'OUI' if is_i1 else 'NON'}")
    if is_blocking:
        print(f"  BLOQUANT: non-I(1) sur 30j ET 60j")
    print()

    return {
        "symbol": symbol,
        "n_clean_sessions": len(clean),
        "windows": windows,
        "is_I1": is_i1,
        "is_blocking": is_blocking,
    }


# ---------------------------------------------------------------------------
# Main — test isolé
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from src.step1_data import run_step1

    data_dir = _PROJECT_ROOT / "data" / "raw"

    for pattern, symbol in [("GC*", "GC"), ("SI*", "SI")]:
        files = list(data_dir.glob(pattern))
        if not files:
            print(f"Pas de fichier {pattern} dans {data_dir}")
            continue

        df = run_step1(files[0], symbol)
        result = run_step2(df, symbol)
        print(f"Résultat {symbol}: I(1)={result['is_I1']}, "
              f"blocking={result['is_blocking']}")
        print("=" * 60)
