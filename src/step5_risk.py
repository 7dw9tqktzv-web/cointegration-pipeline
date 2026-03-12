"""
Step 5 — Phase 4 : Risk Manager (Filtres A/B/C).

Lit le BarState_t, produit un FilterVerdict_t SÉPARÉ.
Ne génère jamais de signal, ne calcule jamais de Kalman.

Source de vérité : docs/recherche/modele_cointegration_v1_FINAL.docx — Section 8.
"""

import sys
from pathlib import Path

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.contracts import Q_KALMAN


# ---------------------------------------------------------------------------
# Filtre A — Qualité de l'Innovation (NIS)
# Type : SUSPENSION TEMPORAIRE — ne bloque JAMAIS une sortie TP/SL.
# ---------------------------------------------------------------------------

def check_filter_a(nis: float, session_state: dict) -> bool:
    """NIS_t < 9.0 ET rolling_NIS_20 < 3.0.

    Input:
        nis:            NIS de la barre courante
        session_state:  état mutable (rolling_nis modifié in-place)

    Output:
        True si filtre OK (pas de blocage)
    """
    session_state["rolling_nis"].append(nis)
    if len(session_state["rolling_nis"]) > 20:
        session_state["rolling_nis"] = session_state["rolling_nis"][-20:]

    rolling_mean = float(np.mean(session_state["rolling_nis"]))

    return (nis < 9.0) and (rolling_mean < 3.0)


# ---------------------------------------------------------------------------
# Filtre B — Vitesse Beta (Seuil Relatif)
# Type : SUSPENSION TEMPORAIRE — ne bloque JAMAIS une sortie TP/SL.
# ---------------------------------------------------------------------------

def check_filter_b(beta_kalman: float, beta_kalman_prev: float) -> bool:
    """|Δβ| / |β_{t-1}| < 0.005.

    Guard : si |β_{t-1}| < 1e-6 → False (division par quasi-zéro).
    beta_kalman_prev est initialisé à β_OLS en Phase 1.

    Input:
        beta_kalman:      β_Kalman courant
        beta_kalman_prev: β_Kalman de la barre précédente

    Output:
        True si filtre OK (variation faible)
    """
    if abs(beta_kalman_prev) < 1e-6:
        return False

    delta_ratio = abs(beta_kalman - beta_kalman_prev) / abs(beta_kalman_prev)
    return delta_ratio < 0.005


# ---------------------------------------------------------------------------
# Filtre C — Dérive Macro (Seuil Adaptatif Absolu)
# Type : COUPE-CIRCUIT DÉFINITIF — irréversible sur la session.
#
# σ_dérive = √(264 × Q_β)    (264 = barres 5min dans session CME 22h)
# seuil_C_abs = 4 × σ_dérive
#
# Valeurs de référence :
#   Metals:       Q_β=1e-7  → seuil=0.02056
#   Equity Index: Q_β=2e-7  → seuil=0.02906
#   Grains:       Q_β=2e-7  → seuil=0.02906
#   Energy:       Q_β=5e-7  → seuil=0.04597
# ---------------------------------------------------------------------------

def check_filter_c(beta_kalman: float, beta_ols: float,
                   classe: str) -> tuple[bool, float]:
    """|β_Kalman_t − β_OLS| < seuil_C_abs.

    Input:
        beta_kalman: β_Kalman courant
        beta_ols:    β OLS fixe (step4)
        classe:      classe d'actifs (pour lookup Q_KALMAN)

    Output:
        (ok, seuil_c_abs) — tuple
    """
    q_beta = Q_KALMAN[classe][1]
    sigma_derive = np.sqrt(264 * q_beta)
    seuil_c_abs = 4.0 * sigma_derive

    drift_abs = abs(beta_kalman - beta_ols)
    ok = drift_abs < seuil_c_abs

    return ok, float(seuil_c_abs)


# ---------------------------------------------------------------------------
# Assemblage Phase 4
# ---------------------------------------------------------------------------

def evaluate_filters(bar_state: dict, session_state: dict,
                     step4_result: dict) -> dict:
    """Évalue les 3 filtres et produit FilterVerdict_t.

    Input:
        bar_state:     BarState_t immuable
        session_state: état mutable (rolling_nis, is_session_killed modifiés)
        step4_result:  paramètres fixes (beta_ols)

    Output:
        FilterVerdict_t dict
    """
    # Si déjà killed → reste killed (IRRÉVERSIBLE)
    if session_state["is_session_killed"]:
        # On met quand même à jour rolling_nis pour le diagnostic
        session_state["rolling_nis"].append(bar_state["nis"])
        if len(session_state["rolling_nis"]) > 20:
            session_state["rolling_nis"] = session_state["rolling_nis"][-20:]
        return {
            "filtre_a_ok": False,
            "filtre_b_ok": False,
            "filtre_c_ok": False,
            "is_session_killed": True,
            "motif_blocage": "session_killed_previous",
        }

    a_ok = check_filter_a(bar_state["nis"], session_state)
    b_ok = check_filter_b(
        bar_state["beta_kalman"], session_state["beta_kalman_prev"]
    )
    c_ok, seuil = check_filter_c(
        bar_state["beta_kalman"], step4_result["beta_ols"],
        session_state["classe"],
    )

    # Filtre C déclenché → session killed
    if not c_ok:
        session_state["is_session_killed"] = True

    motif = None
    if not a_ok:
        motif = "filtre_a"
    elif not b_ok:
        motif = "filtre_b"
    elif not c_ok:
        drift = abs(bar_state["beta_kalman"] - step4_result["beta_ols"])
        motif = f"filtre_c_drift={drift:.4f}_seuil={seuil:.4f}"

    return {
        "filtre_a_ok": a_ok,
        "filtre_b_ok": b_ok,
        "filtre_c_ok": c_ok,
        "is_session_killed": session_state["is_session_killed"],
        "motif_blocage": motif,
    }
