"""
Step 5 — Phases 1 (init), 2 (signal), 3 (Kalman) + boucle session.

Signal Engine (monde statique OLS) + Kalman Engine (monde dynamique).
Le Signal Engine n'accède JAMAIS à β_Kalman.
Le Kalman tourne à CHAQUE barre.

Source de vérité : docs/recherche/modele_cointegration_v1_FINAL.docx — Section 8.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.contracts import Q_KALMAN, PAIRS
from src.step5_risk import evaluate_filters
from src.step5_sizing import compute_sizing


# ---------------------------------------------------------------------------
# σ_rolling — Normalisation Adaptative Intraday (V2.1)
# ---------------------------------------------------------------------------

def compute_sigma_rolling(spread_history: list[float], window: int,
                          sigma_eq_fallback: float) -> float:
    """Calcule l'écart-type glissant du spread sur les N dernières barres.

    Burn-in : si len(spread_history) < window, utilise σ_eq comme fallback.
    En pratique, le trader n'intervient qu'à barre ~90 (01h00 CT),
    donc le burn-in est naturellement résolu.

    Input:
        spread_history:   liste des spreads de la session en cours (barres 0 à t)
        window:           nombre de barres pour le calcul (paramètre à tester)
        sigma_eq_fallback: σ_eq de step4, utilisé pendant le burn-in

    Output:
        σ_rolling (float, toujours > 0)
    """
    if len(spread_history) < window:
        if len(spread_history) < 2:
            return sigma_eq_fallback
        # Burn-in partiel : calculer sur ce qu'on a si >= min_bars
        min_bars = max(10, window // 4)
        if len(spread_history) >= min_bars:
            sigma = float(np.std(spread_history, ddof=1))
            return max(sigma, 1e-10)
        return sigma_eq_fallback

    sigma = float(np.std(spread_history[-window:], ddof=1))
    return max(sigma, 1e-10)


# ---------------------------------------------------------------------------
# Phase 1 — Initialisation de Session
# ---------------------------------------------------------------------------

def _compute_t_limite(hl_operational: float, pair_config: dict) -> int:
    """T_limite en minutes depuis minuit CT.

    T_close_session = 15:30 CT = 930 min.
    T_limite = min(T_close_session - hl_operational*5, T_close_pit).

    Input:
        hl_operational: half-life opérationnel en barres 5min
        pair_config:    config paire (t_close_pit)

    Output:
        T_limite en minutes depuis minuit CT
    """
    t_close_session = 15 * 60 + 30  # 930 min

    pit = pair_config.get("t_close_pit")
    if pit is None:
        t_close_pit = t_close_session
    else:
        h, m = map(int, pit.split(":"))
        t_close_pit = h * 60 + m

    t_lim_from_hl = t_close_session - hl_operational * 5
    return min(int(t_lim_from_hl), t_close_pit)


def init_session(step4_result: dict, pair_config: dict,
                 sigma_rolling_window: int = 20,
                 sl_threshold: float = 3.0) -> dict:
    """Phase 1 — Initialise tous les états de session.

    Appelée UNE fois par session (à 17h30 CT).

    Input:
        step4_result:         dict sortie de run_step4
        pair_config:          PairConfig depuis config/contracts.py
        sigma_rolling_window: fenêtre σ_rolling en barres (V2.1)
        sl_threshold:         seuil SL en unités de σ (défaut 3.0)

    Output:
        session_state dict mutable (modifié barre par barre)
    """
    alpha_ols = step4_result["alpha_ols"]
    beta_ols = step4_result["beta_ols"]
    se_alpha = step4_result["se_alpha"]
    se_beta = step4_result["se_beta"]
    resid_var = step4_result["resid_var"]
    hl_operational = step4_result["hl_operational"]

    classe = pair_config["classe"]
    q_alpha, q_beta = Q_KALMAN[classe]

    return {
        # Signal Engine
        "is_armed_long": False,
        "is_armed_short": False,
        "position": None,       # None | "LONG" | "SHORT"
        "entry_bar": None,      # BarState_t de l'entrée

        # Kalman Engine
        "x": np.array([alpha_ols, beta_ols]),
        "P": np.diag([
            max(se_alpha ** 2, 1e-4),
            max(se_beta ** 2, 1e-4),
        ]),

        # Risk Manager
        "is_session_killed": False,
        "rolling_nis": [],
        "beta_kalman_prev": beta_ols,
        "classe": classe,

        # Kalman fixed params
        "Q": np.diag([q_alpha, q_beta]),
        "R": resid_var,

        # Time-lock
        "t_limite": _compute_t_limite(hl_operational, pair_config),

        # Trades log
        "trades": [],

        # V2.1 — σ_rolling
        "spread_history": [],
        "sigma_rolling_window": sigma_rolling_window,

        # Seuils paramétrables
        "sl_threshold": sl_threshold,
    }


# ---------------------------------------------------------------------------
# Phase 2 — Signal Engine (monde STATIQUE OLS)
# ---------------------------------------------------------------------------

def compute_signal(row, session_state: dict, step4_result: dict,
                   current_time_min: int) -> tuple[str | None, float, float, float]:
    """Calcule le spread, σ_rolling, Z-score et détermine le signal.

    V2.1 : le Z-score utilise σ_rolling (dynamique intraday) au lieu de σ_eq.
    σ_eq reste disponible dans step4_result pour diagnostic.
    Le Signal Engine n'accède JAMAIS à β_Kalman.

    Input:
        row:              barre 5min (price_a, price_b)
        session_state:    état mutable
        step4_result:     paramètres fixes
        current_time_min: minutes depuis minuit CT

    Output:
        (signal, spread, z, sigma_rolling)
    """
    alpha_ols = step4_result["alpha_ols"]
    beta_ols = step4_result["beta_ols"]
    theta_ou = step4_result["theta_ou"]
    sigma_eq = step4_result["sigma_eq"]

    log_a = np.log(row["price_a"])
    log_b = np.log(row["price_b"])
    # Spread brut OLS — soustraire θ_OU ne changerait pas le std
    spread = log_a - alpha_ols - beta_ols * log_b

    # V2.1 : accumuler le spread et calculer σ_rolling
    session_state["spread_history"].append(spread)
    sigma_rolling = compute_sigma_rolling(
        session_state["spread_history"],
        session_state["sigma_rolling_window"],
        sigma_eq,
    )

    z = (spread - theta_ou) / sigma_rolling

    # Time-Lock : désarmer, pas de nouvelle entrée
    if current_time_min >= session_state["t_limite"]:
        session_state["is_armed_long"] = False
        session_state["is_armed_short"] = False

    # --- Machine à états — PRIORITÉ DES SIGNAUX ---
    signal = None
    position = session_state["position"]
    sl = session_state["sl_threshold"]

    # 1. SESSION_CLOSE — 5ème motif (audit #1)
    if current_time_min >= 15 * 60 + 25 and position is not None:
        return ("SESSION_CLOSE", float(spread), float(z), float(sigma_rolling))

    # 2. STOP LOSS
    if position == "LONG" and z < -sl:
        signal = "SL"
    elif position == "SHORT" and z > sl:
        signal = "SL"

    # 3. TAKE PROFIT
    elif position is not None and abs(z) < 0.5:
        signal = "TP"

    # 4. DÉSARMEMENT sans position en zone SL
    elif position is None and session_state["is_armed_long"] and z < -sl:
        session_state["is_armed_long"] = False
    elif position is None and session_state["is_armed_short"] and z > sl:
        session_state["is_armed_short"] = False

    # 5. DÉCLENCHEMENT (seulement si pas en time-lock et pas de position)
    elif position is None and current_time_min < session_state["t_limite"]:
        if session_state["is_armed_long"] and z > -2.0:
            signal = "ENTRY_LONG"
            session_state["is_armed_long"] = False
        elif session_state["is_armed_short"] and z < 2.0:
            signal = "ENTRY_SHORT"
            session_state["is_armed_short"] = False

    # 6. ARMEMENT (indépendant, toujours évalué si pas de position + pas time-lock)
    #    Pas d'armement en zone SL
    if position is None and current_time_min < session_state["t_limite"]:
        if z < -2.0 and z >= -sl:
            session_state["is_armed_long"] = True
        if z > 2.0 and z <= sl:
            session_state["is_armed_short"] = True

    return (signal, float(spread), float(z), float(sigma_rolling))


# ---------------------------------------------------------------------------
# Phase 3 — Kalman Engine (tourne à CHAQUE barre)
# ---------------------------------------------------------------------------

def kalman_update(row, session_state: dict) -> dict:
    """Mise à jour Kalman pour une barre.

    7 étapes — PROHIBITION #5 : Joseph form obligatoire pour P.

    Input:
        row:           barre 5min (price_a, price_b)
        session_state: état mutable (x, P modifiés in-place)

    Output:
        dict avec alpha_kalman, beta_kalman, nis, innovation, S
    """
    x = session_state["x"]
    P = session_state["P"]
    Q = session_state["Q"]
    R = session_state["R"]

    log_a = np.log(row["price_a"])
    log_b = np.log(row["price_b"])

    # Étape 1 — Vecteur d'observation
    H = np.array([1.0, log_b])

    # Étape 2 — Prédiction a priori (random walk sur état)
    x_pred = x.copy()
    P_pred = P + Q

    # Étape 3 — Innovation
    e = log_a - H @ x_pred

    # Étape 4 — Variance de l'innovation
    S = H @ P_pred @ H + R

    # Étape 5 — Kalman Gain
    K = P_pred @ H / S

    # Étape 6 — Mise à jour (FORME DE JOSEPH — PROHIBITION #5)
    x_new = x_pred + K * e
    I_KH = np.eye(2) - np.outer(K, H)
    P_new = I_KH @ P_pred @ I_KH.T + np.outer(K, K) * R

    # Étape 7 — NIS
    nis = (e ** 2) / S

    # Mettre à jour l'état
    session_state["x"] = x_new
    session_state["P"] = P_new

    return {
        "alpha_kalman": float(x_new[0]),
        "beta_kalman": float(x_new[1]),
        "nis": float(nis),
        "innovation": float(e),
        "S": float(S),
    }


# ---------------------------------------------------------------------------
# Helpers — ouverture / fermeture de position
# ---------------------------------------------------------------------------

_SIGNAL_TO_MOTIF = {
    "TP": "TAKE_PROFIT",
    "SL": "STOP_LOSS",
    "SESSION_CLOSE": "SESSION_CLOSE",
    "SORTIE_FORCEE": "SORTIE_FORCEE",
}


def _close_position(bar_state: dict, exit_signal: str,
                    session_state: dict) -> None:
    """Ferme la position courante et complète le trade."""
    trade = session_state["trades"][-1]
    trade["exit_timestamp"] = bar_state["timestamp"]
    trade["exit_motif"] = _SIGNAL_TO_MOTIF.get(exit_signal, exit_signal)
    trade["exit_z"] = bar_state["z_score"]
    trade["beta_kalman_exit"] = bar_state["beta_kalman"]
    trade["exit_price_a"] = bar_state["raw_price_a"]
    trade["exit_price_b"] = bar_state["raw_price_b"]

    session_state["position"] = None
    session_state["entry_bar"] = None


def _open_position(bar_state: dict, signal: str, sizing: dict,
                   session_state: dict) -> None:
    """Ouvre une nouvelle position et logue le trade."""
    direction = "LONG" if signal == "ENTRY_LONG" else "SHORT"

    trade = {
        # Entrée
        "entry_timestamp": bar_state["timestamp"],
        "entry_motif": "ENTREE_ARMEE",
        "direction": direction,
        "entry_z": bar_state["z_score"],
        "beta_kalman_entry": bar_state["beta_kalman"],
        "entry_price_a": bar_state["raw_price_a"],
        "entry_price_b": bar_state["raw_price_b"],
        "sizing": sizing,
        # Sortie (rempli à la fermeture)
        "exit_timestamp": None,
        "exit_motif": None,
        "exit_z": None,
        "beta_kalman_exit": None,
        "exit_price_a": None,
        "exit_price_b": None,
    }

    session_state["trades"].append(trade)
    session_state["position"] = direction
    session_state["entry_bar"] = bar_state


# ---------------------------------------------------------------------------
# Exécution signal + filtres + sizing
# ---------------------------------------------------------------------------

def _execute_signal(bar_state: dict, verdict: dict,
                    session_state: dict, step4_result: dict) -> None:
    """Orchestre Phase 4 (verdict) + Phase 5 (sizing).

    - Sorties (TP/SL/SESSION_CLOSE) toujours exécutées.
    - Filtres A/B ne bloquent JAMAIS les sorties.
    - Filtre C force SORTIE_FORCEE si position ouverte.
    - Entrées : seulement si 3 filtres OK et sizing valide.
    """
    signal = bar_state["signal"]

    # SORTIE FORCÉE — Filtre C (indépendant du signal, priorité haute)
    if verdict["is_session_killed"] and session_state["position"] is not None:
        # Ne pas overrider une sortie normale (TP/SL/SESSION_CLOSE)
        if signal not in ("TP", "SL", "SESSION_CLOSE"):
            _close_position(bar_state, "SORTIE_FORCEE", session_state)
            return

    if signal is None:
        return

    # SORTIES — toujours exécutées
    if signal in ("TP", "SL", "SESSION_CLOSE"):
        _close_position(bar_state, signal, session_state)
        return

    # ENTRÉES — vérifier les 3 filtres
    if signal in ("ENTRY_LONG", "ENTRY_SHORT"):
        if (verdict["filtre_a_ok"] and verdict["filtre_b_ok"]
                and not verdict["is_session_killed"]):
            sizing = compute_sizing(bar_state, step4_result)
            if sizing["is_valid"]:
                _open_position(bar_state, signal, sizing, session_state)


# ---------------------------------------------------------------------------
# Diagnostics session
# ---------------------------------------------------------------------------

def _compute_session_diagnostics(bar_states: list,
                                 session_state: dict) -> dict:
    """Calcule des métriques résumées de la session."""
    nis_values = [bs["nis"] for bs in bar_states]
    p_final = session_state["P"]
    eigvals = np.linalg.eigvalsh(p_final)

    return {
        "n_bars": len(bar_states),
        "n_trades": len(session_state["trades"]),
        "nis_mean": float(np.mean(nis_values)) if nis_values else 0.0,
        "nis_max": float(np.max(nis_values)) if nis_values else 0.0,
        "p_eigenvalues": eigvals.tolist(),
        "p_is_psd": bool(np.all(eigvals > 0)),
        "session_killed": session_state["is_session_killed"],
        "t_limite": session_state["t_limite"],
    }


# ---------------------------------------------------------------------------
# Boucle principale par session
# ---------------------------------------------------------------------------

def run_session(df_session: pd.DataFrame, step4_result: dict,
                pair_config: dict,
                sigma_rolling_window: int = 20,
                sl_threshold: float = 3.0) -> dict:
    """Exécute les phases 1-5 sur une session complète.

    Input:
        df_session:           DataFrame 5min d'UNE session avec colonnes
                              price_a, price_b et DatetimeIndex
        step4_result:         dict sortie de run_step4
        pair_config:          PairConfig depuis config/contracts.py
        sigma_rolling_window: fenêtre σ_rolling en barres (V2.1)
        sl_threshold:         seuil SL en unités de σ (défaut 3.0)

    Output:
        dict avec bar_states (liste), trades (liste), diagnostics
    """
    session_state = init_session(step4_result, pair_config,
                                 sigma_rolling_window, sl_threshold)
    bar_states = []

    for idx, row in df_session.iterrows():
        current_time_min = idx.hour * 60 + idx.minute

        # Phase 2 + Phase 3 (conceptuellement parallèles)
        signal, spread_val, z_val, sigma_rolling_val = compute_signal(
            row, session_state, step4_result, current_time_min
        )
        kalman = kalman_update(row, session_state)

        # Barrière → BarState_t IMMUABLE
        bar_state = {
            "timestamp": idx,
            "raw_price_a": float(row["price_a"]),
            "raw_price_b": float(row["price_b"]),
            "spread": spread_val,
            "z_score": z_val,
            "sigma_rolling": sigma_rolling_val,
            "signal": signal,
            "beta_kalman": kalman["beta_kalman"],
            "alpha_kalman": kalman["alpha_kalman"],
            "nis": kalman["nis"],
        }

        # Phase 4 — Risk Manager
        verdict = evaluate_filters(bar_state, session_state, step4_result)

        # Phase 5 — Sizing + exécution (conditionnel)
        _execute_signal(bar_state, verdict, session_state, step4_result)

        # Mettre à jour beta_kalman_prev pour Filtre B
        session_state["beta_kalman_prev"] = kalman["beta_kalman"]

        bar_states.append(bar_state)

    return {
        "bar_states": bar_states,
        "trades": session_state["trades"],
        "diagnostics": _compute_session_diagnostics(bar_states, session_state),
    }


if __name__ == "__main__":
    print("step5_engine — utiliser run_session() depuis le backtester.")
