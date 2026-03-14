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

from config.contracts import Q_KALMAN, PAIRS, HL_INTRADAY_P75
from src.step5_risk import evaluate_filters
from src.step5_sizing import compute_sizing


# ---------------------------------------------------------------------------
# σ_rolling — Normalisation Adaptative Intraday (V2.1, conserve pour compat)
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
# Z-score intraday V2.2 — mu_rolling + sigma_rolling meme fenetre
# ---------------------------------------------------------------------------

def compute_z_intraday(spread_history: list[float],
                       window: int) -> tuple[float, float, float]:
    """Calcule le Z-score intraday auto-coherent.

    Z = (spread_t - mu_rolling) / sigma_rolling
    mu et sigma sont estimes sur la meme fenetre N.
    Z est mecaniquement borne — pas de dependance a theta_OU ni sigma_eq.
    Pendant le burn-in (historique < window), Z = 0 (pas de signal).

    Input:
        spread_history: liste des spreads de la session (barres 0 a t)
        window:         fenetre rolling en barres

    Output:
        (z, mu_rolling, sigma_rolling)
    """
    if len(spread_history) < window:
        # Burn-in : pas de signal
        return (0.0, 0.0, 0.0)

    recent = spread_history[-window:]
    mu = float(np.mean(recent))
    sigma = float(np.std(recent, ddof=1))
    sigma = max(sigma, 1e-10)

    spread_t = spread_history[-1]
    z = (spread_t - mu) / sigma

    return (z, mu, sigma)


# ---------------------------------------------------------------------------
# Phase 1 — Initialisation de Session
# ---------------------------------------------------------------------------

def _compute_bias(first_row: dict, step4_result: dict) -> str:
    """Biais directionnel V2.2 — couche 1 vers couche 2.

    Z_LT = (spread_ouverture - theta_OU) / sigma_eq
    Si Z_LT > 0 : spread au-dessus de l'equilibre long terme -> SHORT seulement
    Si Z_LT < 0 : spread en dessous -> LONG seulement

    Input:
        first_row:    premiere barre de la session (price_a, price_b)
        step4_result: parametres OU (theta_ou, sigma_eq, alpha_ols, beta_ols)

    Output:
        "LONG" ou "SHORT"
    """
    alpha = step4_result["alpha_ols"]
    beta = step4_result["beta_ols"]
    theta = step4_result["theta_ou"]
    sigma_eq = step4_result["sigma_eq"]

    log_a = np.log(first_row["price_a"])
    log_b = np.log(first_row["price_b"])
    spread_open = log_a - alpha - beta * log_b
    z_lt = (spread_open - theta) / sigma_eq

    return "SHORT" if z_lt > 0 else "LONG"


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
                 sl_threshold: float = 3.0,
                 direct_entry: bool = False,
                 tp_level: float = 0.5,
                 use_v2_zscore: bool = False,
                 first_row: dict | None = None,
                 pair_name: str | None = None) -> dict:
    """Phase 1 — Initialise tous les états de session.

    Appelée UNE fois par session (à 17h30 CT).

    Input:
        step4_result:         dict sortie de run_step4
        pair_config:          PairConfig depuis config/contracts.py
        sigma_rolling_window: fenêtre σ_rolling en barres (V2.1)
        sl_threshold:         seuil SL en unités de σ (défaut 3.0)
        direct_entry:         True = entree au 1er franchissement, pas de arm-then-trigger
        tp_level:             seuil TP (defaut 0.5 = |z| < 0.5 en mode classique)
        use_v2_zscore:        True = Z intraday V2.2 (mu_rolling + sigma_rolling)
        first_row:            premiere barre de la session (pour biais directionnel V2.2)

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

    # HL_intraday P75 pour T_limite V2.2
    hl_intraday_p75 = HL_INTRADAY_P75.get(pair_name) if pair_name else None

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

        # Time-lock — V2.2 : utiliser HL_intraday P75 au lieu de HL multi-jour
        "t_limite": _compute_t_limite(
            hl_intraday_p75 if use_v2_zscore and hl_intraday_p75 else hl_operational,
            pair_config,
        ),

        # Trades log
        "trades": [],

        # V2.1 — σ_rolling
        "spread_history": [],
        "sigma_rolling_window": sigma_rolling_window,

        # Seuils paramétrables
        "sl_threshold": sl_threshold,
        "direct_entry": direct_entry,
        "tp_level": tp_level,

        # V2.2 — Z intraday
        "use_v2_zscore": use_v2_zscore,
        "bias": _compute_bias(first_row, step4_result) if use_v2_zscore and first_row else None,

        # V2.2 — sorties spread-space (figes a l'entree)
        "spread_entry": None,
        "sigma_entry": None,
    }


# ---------------------------------------------------------------------------
# Phase 2 — Signal Engine (monde STATIQUE OLS)
# ---------------------------------------------------------------------------

def compute_signal(row, session_state: dict, step4_result: dict,
                   current_time_min: int) -> tuple[str | None, float, float, float]:
    """Calcule le spread, Z-score et détermine le signal.

    Deux modes :
    - V2.1 (use_v2_zscore=False) : Z = (spread - theta_OU) / sigma_rolling
    - V2.2 (use_v2_zscore=True)  : Z = (spread - mu_rolling) / sigma_rolling
      avec mu et sigma sur la meme fenetre, entree directe, biais directionnel.

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
    # Spread brut OLS — soustraire theta_OU ne changerait pas le std
    spread = log_a - alpha_ols - beta_ols * log_b

    # Accumuler le spread
    session_state["spread_history"].append(spread)

    # Calcul du Z-score selon le mode
    if session_state["use_v2_zscore"]:
        # V2.2 : Z intraday auto-coherent (mu + sigma meme fenetre)
        z, mu_rolling, sigma_rolling = compute_z_intraday(
            session_state["spread_history"],
            session_state["sigma_rolling_window"],
        )
    else:
        # V2.1 : Z = (spread - theta_OU) / sigma_rolling
        sigma_rolling = compute_sigma_rolling(
            session_state["spread_history"],
            session_state["sigma_rolling_window"],
            sigma_eq,
        )
        z = (spread - theta_ou) / sigma_rolling

    # --- Machine a etats --- PRIORITE DES SIGNAUX ---
    signal = None
    position = session_state["position"]
    sl = session_state["sl_threshold"]
    tp_lv = session_state["tp_level"]
    bias = session_state.get("bias")
    is_v2 = session_state["use_v2_zscore"]

    # Time-Lock
    if current_time_min >= session_state["t_limite"]:
        session_state["is_armed_long"] = False
        session_state["is_armed_short"] = False

    # 1. SESSION_CLOSE
    if current_time_min >= 15 * 60 + 25 and position is not None:
        return ("SESSION_CLOSE", float(spread), float(z), float(sigma_rolling))

    # 2-3. STOP LOSS + TAKE PROFIT
    if position is not None:
        spread_e = session_state.get("spread_entry")
        sigma_e = session_state.get("sigma_entry")

        if is_v2 and spread_e is not None and sigma_e is not None and sigma_e > 0:
            # V2.2 : sorties en spread-space avec references figees a l'entree
            # SL a 1.5 * sigma_entry, TP a tp_level * sigma_entry
            if position == "LONG":
                if spread < spread_e - 1.5 * sigma_e:
                    signal = "SL"
                elif spread > spread_e + tp_lv * sigma_e:
                    signal = "TP"
            else:  # SHORT
                if spread > spread_e + 1.5 * sigma_e:
                    signal = "SL"
                elif spread < spread_e - tp_lv * sigma_e:
                    signal = "TP"
        else:
            # V2.1 : sorties en Z-score
            if position == "LONG" and z < -sl:
                signal = "SL"
            elif position == "SHORT" and z > sl:
                signal = "SL"
            elif session_state["direct_entry"]:
                if position == "LONG" and z >= tp_lv:
                    signal = "TP"
                elif position == "SHORT" and z <= -tp_lv:
                    signal = "TP"
            else:
                if abs(z) < tp_lv:
                    signal = "TP"

    # 4. ENTREES
    if signal is None and position is None:
        if is_v2:
            # V2.2 : entree directe + filtre biais directionnel
            if current_time_min < session_state["t_limite"]:
                if z <= -2.0 and z >= -sl and bias == "LONG":
                    signal = "ENTRY_LONG"
                elif z >= 2.0 and z <= sl and bias == "SHORT":
                    signal = "ENTRY_SHORT"

        elif session_state["direct_entry"]:
            # V2.1 entree directe (sans biais)
            if current_time_min < session_state["t_limite"]:
                if z <= -2.0 and z >= -sl:
                    signal = "ENTRY_LONG"
                elif z >= 2.0 and z <= sl:
                    signal = "ENTRY_SHORT"

        else:
            # V2.1 arm-then-trigger classique
            if session_state["is_armed_long"] and z < -sl:
                session_state["is_armed_long"] = False
            elif session_state["is_armed_short"] and z > sl:
                session_state["is_armed_short"] = False
            elif current_time_min < session_state["t_limite"]:
                if session_state["is_armed_long"] and z > -2.0:
                    signal = "ENTRY_LONG"
                    session_state["is_armed_long"] = False
                elif session_state["is_armed_short"] and z < 2.0:
                    signal = "ENTRY_SHORT"
                    session_state["is_armed_short"] = False

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

    # V2.2 : figer spread_entry et sigma_entry pour sorties spread-space
    session_state["spread_entry"] = bar_state.get("spread", 0.0)
    session_state["sigma_entry"] = bar_state.get("sigma_rolling", 0.0)

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
                sl_threshold: float = 3.0,
                direct_entry: bool = False,
                tp_level: float = 0.5,
                use_v2_zscore: bool = False,
                pair_name: str | None = None) -> dict:
    """Exécute les phases 1-5 sur une session complète.

    Input:
        df_session:           DataFrame 5min d'UNE session avec colonnes
                              price_a, price_b et DatetimeIndex
        step4_result:         dict sortie de run_step4
        pair_config:          PairConfig depuis config/contracts.py
        sigma_rolling_window: fenêtre σ_rolling en barres (V2.1)
        sl_threshold:         seuil SL en unités de σ (défaut 3.0)
        direct_entry:         True = entree directe au 1er franchissement
        tp_level:             seuil TP (defaut 0.5)
        use_v2_zscore:        True = Z intraday V2.2

    Output:
        dict avec bar_states (liste), trades (liste), diagnostics
    """
    # Premiere barre pour le biais directionnel V2.2
    first_row = None
    if use_v2_zscore and len(df_session) > 0:
        row0 = df_session.iloc[0]
        first_row = {"price_a": float(row0["price_a"]),
                     "price_b": float(row0["price_b"])}

    session_state = init_session(step4_result, pair_config,
                                 sigma_rolling_window, sl_threshold,
                                 direct_entry, tp_level,
                                 use_v2_zscore, first_row, pair_name)
    bar_states = []
    kalman_burnin = 5  # barres pour stabiliser le Kalman avant filtre C

    for bar_idx, (idx, row) in enumerate(df_session.iterrows()):
        current_time_min = idx.hour * 60 + idx.minute

        # Phase 2 + Phase 3 (conceptuellement parallèles)
        signal, spread_val, z_val, sigma_rolling_val = compute_signal(
            row, session_state, step4_result, current_time_min
        )
        kalman = kalman_update(row, session_state)

        # V2.2 : figer beta_ref apres burn-in Kalman (5 barres)
        # Le Kalman a le droit de corriger l'initialisation stale.
        # Le filtre C ne surveille que la derive intra-session reelle.
        if use_v2_zscore and bar_idx == kalman_burnin:
            session_state["beta_ref"] = kalman["beta_kalman"]

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
        # Pendant le burn-in Kalman V2.2, pas de filtre C (beta_ref pas encore fige)
        if use_v2_zscore and bar_idx < kalman_burnin:
            # Skip filtre C pendant le burn-in — on laisse le Kalman converger
            session_state["rolling_nis"].append(kalman["nis"])
            if len(session_state["rolling_nis"]) > 20:
                session_state["rolling_nis"] = session_state["rolling_nis"][-20:]
            verdict = {"filtre_a_ok": True, "filtre_b_ok": True,
                       "filtre_c_ok": True, "is_session_killed": False,
                       "motif_blocage": None}
        else:
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
