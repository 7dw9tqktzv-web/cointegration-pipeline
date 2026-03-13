"""
Backtester — Boucle multi-session, PnL, coûts, métriques.

Source de vérité : docs/recherche/modele_cointegration_v1_FINAL.docx — §9-10.

Architecture :
    Pour chaque session T :
        1. Fenêtre calibration (30 sessions propres avant T, anti-look-ahead)
        2. Steps 2-3-4 sur fenêtre calibration
        3. Step 5 (Kalman + signal + risk + sizing) sur session T
        4. PnL brut + coûts (3 scénarios slippage) → PnL net
        5. Agrégation quotidienne + métriques V1
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.contracts import CONTRACTS, COSTS_RT, PAIRS, find_micro
from src.step2_stationarity import run_step2
from src.step3_cointegration import run_step3
from src.step4_ou import run_step4
from src.step5_engine import run_session


# ---------------------------------------------------------------------------
# Sélection fenêtre de calibration
# ---------------------------------------------------------------------------

def select_calibration_window(
    df_a: pd.DataFrame, df_b: pd.DataFrame,
    target_session: str,
    pair_config: dict,
    n_sessions: int = 30,
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Sélectionne les n sessions propres AVANT target_session.

    ANTI-LOOK-AHEAD : target_session est strictement exclue.
    Exclusion rollover : ±N sessions autour de chaque rollover détecté,
    avec N = pair_config["rollover_excl"].

    Input:
        df_a, df_b:       DataFrames 5min complets (step1)
        target_session:   session_id de la session à trader (YYYYMMDD)
        pair_config:      PairConfig (rollover_excl, etc.)
        n_sessions:       nombre de sessions de calibration (30)

    Output:
        (df_a_calib, df_b_calib) DataFrames filtrés, ou None si insuffisant
    """
    rollover_excl = pair_config["rollover_excl"]

    # 1. Sessions communes (intersection A ∩ B)
    sessions_a = set(df_a["session_id"].unique())
    sessions_b = set(df_b["session_id"].unique())
    all_sessions = sorted(sessions_a & sessions_b)

    # 2. Strictement avant target
    prior_sessions = [s for s in all_sessions if s < target_session]

    # 3. Identifier les sessions rollover
    rollover_sessions: set[str] = set()
    for df in [df_a, df_b]:
        if "rollover_discontinuity" in df.columns:
            flagged = df[df["rollover_discontinuity"]]["session_id"].unique()
            rollover_sessions.update(flagged)

    # 4. Exclure rollover ± N voisines
    excluded: set[str] = set()
    for roll_sid in rollover_sessions:
        if roll_sid not in prior_sessions:
            continue
        roll_idx = prior_sessions.index(roll_sid)
        for offset in range(-rollover_excl, rollover_excl + 1):
            idx = roll_idx + offset
            if 0 <= idx < len(prior_sessions):
                excluded.add(prior_sessions[idx])

    # 5. Exclure low_liquidity
    for df in [df_a, df_b]:
        if "low_liquidity_day" in df.columns:
            low_liq = df[df["low_liquidity_day"]]["session_id"].unique()
            excluded.update(low_liq)

    # 6. Sessions propres
    clean_sessions = [s for s in prior_sessions if s not in excluded]

    # 7. Prendre les n dernières
    if len(clean_sessions) < n_sessions:
        return None
    selected = set(clean_sessions[-n_sessions:])

    # 8. Filtrer les DataFrames
    df_a_calib = df_a[df_a["session_id"].isin(selected)].copy()
    df_b_calib = df_b[df_b["session_id"].isin(selected)].copy()
    return (df_a_calib, df_b_calib)


# ---------------------------------------------------------------------------
# Préparation DataFrame session T
# ---------------------------------------------------------------------------

def prepare_session_df(df_a: pd.DataFrame, df_b: pd.DataFrame,
                       session_id: str) -> pd.DataFrame | None:
    """Prépare le DataFrame pour run_session sur la session T.

    Inner join sur timestamps communs. Renomme 'price' → 'price_a' / 'price_b'.

    Output: DataFrame avec colonnes price_a, price_b et DatetimeIndex,
            ou None si session absente d'un des deux actifs.
    """
    mask_a = df_a["session_id"] == session_id
    mask_b = df_b["session_id"] == session_id

    if mask_a.sum() == 0 or mask_b.sum() == 0:
        return None

    sa = df_a.loc[mask_a, ["price"]].rename(columns={"price": "price_a"})
    sb = df_b.loc[mask_b, ["price"]].rename(columns={"price": "price_b"})

    df_session = sa.join(sb, how="inner")
    if len(df_session) == 0:
        return None
    return df_session


# ---------------------------------------------------------------------------
# PnL Brut
# ---------------------------------------------------------------------------

def compute_pnl_brut(trade: dict, step4_result: dict) -> float:
    """PnL brut en dollars d'un trade complété.

    PROHIBITION #3 : utiliser multiplier, pas tick_value.
    Règle 5 : sizing fixé à l'ENTRÉE — β_Kalman_SORTIE non utilisé.

    Input:
        trade:         dict trade complété (entry/exit prices + sizing)
        step4_result:  pour symbol_a, symbol_b, direction

    Output:
        PnL brut en dollars (positif = gain, négatif = perte)
    """
    ols_direction = step4_result["direction"]

    # Identifier dep/indep selon direction OLS
    if ols_direction == "A_B":
        entry_price_dep = trade["entry_price_a"]
        entry_price_indep = trade["entry_price_b"]
        exit_price_dep = trade["exit_price_a"]
        exit_price_indep = trade["exit_price_b"]
        dep_sym = step4_result["symbol_a"]
        indep_sym = step4_result["symbol_b"]
    else:
        entry_price_dep = trade["entry_price_b"]
        entry_price_indep = trade["entry_price_a"]
        exit_price_dep = trade["exit_price_b"]
        exit_price_indep = trade["exit_price_a"]
        dep_sym = step4_result["symbol_b"]
        indep_sym = step4_result["symbol_a"]

    sizing = trade["sizing"]
    mult_dep_std = CONTRACTS[dep_sym]["multiplier"]
    mult_indep_std = CONTRACTS[indep_sym]["multiplier"]

    # Micro Leg B (indep)
    micro_sym_b = sizing["micro_sym_B"]
    mult_indep_micro = CONTRACTS[micro_sym_b]["multiplier"] if micro_sym_b else 0

    # Micro Leg A (dep) — Q_A_micro = 0 en V1, code générique
    micro_sym_a = find_micro(dep_sym)
    mult_dep_micro = CONTRACTS[micro_sym_a]["multiplier"] if micro_sym_a else 0

    # PnL Leg dep (LONG dans un LONG spread)
    delta_dep = exit_price_dep - entry_price_dep
    pnl_dep = (delta_dep * sizing["Q_A_std"] * mult_dep_std
               + delta_dep * sizing["Q_A_micro"] * mult_dep_micro)

    # PnL Leg indep (SHORT dans un LONG spread)
    delta_indep = entry_price_indep - exit_price_indep
    pnl_indep = (delta_indep * sizing["Q_B_std"] * mult_indep_std
                 + delta_indep * sizing["Q_B_micro"] * mult_indep_micro)

    if trade["direction"] == "LONG":
        return pnl_dep + pnl_indep
    else:  # SHORT spread → inverser
        return -pnl_dep - pnl_indep


# ---------------------------------------------------------------------------
# Coûts de transaction — PROHIBITION #7
# ---------------------------------------------------------------------------

def compute_spread_cost_rt(trade: dict, step4_result: dict,
                           slippage_mult: float = 1.0) -> float:
    """Coût total round-trip du spread trade.

    PROHIBITION #7 : appelé UNE SEULE FOIS par trade.
    Le multiplicateur s'applique UNIQUEMENT au slippage, pas aux commissions.

    Input:
        trade:          dict trade avec sizing
        step4_result:   pour symbol_a, symbol_b, direction
        slippage_mult:  1.0 (base), 1.5 (robustesse), 2.0 (pessimiste)

    Output:
        Coût en dollars (toujours positif)
    """
    sizing = trade["sizing"]
    ols_direction = step4_result["direction"]

    if ols_direction == "A_B":
        dep_sym = step4_result["symbol_a"]
        indep_sym = step4_result["symbol_b"]
    else:
        dep_sym = step4_result["symbol_b"]
        indep_sym = step4_result["symbol_a"]

    micro_sym_b = sizing["micro_sym_B"]
    micro_sym_a = find_micro(dep_sym)

    # Coût Leg A (dep) — std
    cost_dep = 0.0
    if sizing["Q_A_std"] > 0:
        cost_dep += sizing["Q_A_std"] * (
            COSTS_RT[dep_sym]["comm_rt"]
            + COSTS_RT[dep_sym]["slip_rt"] * slippage_mult
        )
    # Coût Leg A micro
    if sizing["Q_A_micro"] > 0 and micro_sym_a is not None:
        cost_dep += sizing["Q_A_micro"] * (
            COSTS_RT[micro_sym_a]["comm_rt"]
            + COSTS_RT[micro_sym_a]["slip_rt"] * slippage_mult
        )

    # Coût Leg B (indep) — std
    cost_indep = 0.0
    if sizing["Q_B_std"] > 0:
        cost_indep += sizing["Q_B_std"] * (
            COSTS_RT[indep_sym]["comm_rt"]
            + COSTS_RT[indep_sym]["slip_rt"] * slippage_mult
        )
    # Coût Leg B micro
    if sizing["Q_B_micro"] > 0 and micro_sym_b is not None:
        cost_indep += sizing["Q_B_micro"] * (
            COSTS_RT[micro_sym_b]["comm_rt"]
            + COSTS_RT[micro_sym_b]["slip_rt"] * slippage_mult
        )

    return cost_dep + cost_indep


# ---------------------------------------------------------------------------
# Agrégation PnL quotidien
# ---------------------------------------------------------------------------

def aggregate_daily_pnl(all_trades: list[dict],
                        all_session_ids: list[str]) -> pd.DataFrame:
    """Agrège le PnL par session_id (= jour de trading).

    Sessions sans trade → PnL = 0 (pas de lignes manquantes).
    Crucial pour le Sharpe : jours sans trade pénalisent la moyenne.

    Input:
        all_trades:      liste de tous les trades complétés
        all_session_ids: tous les session_ids de la période (tradées + skippées)

    Output:
        DataFrame index=session_id, colonnes pnl_net_1x, pnl_net_1_5x, pnl_net_2x
    """
    # Base : toutes les sessions à 0
    daily = pd.DataFrame(
        {"pnl_net_1x": 0.0, "pnl_net_1_5x": 0.0, "pnl_net_2x": 0.0},
        index=all_session_ids,
    )
    daily.index.name = "session_id"

    # Ajouter le PnL des trades
    for trade in all_trades:
        sid = trade.get("session_id")
        if sid is None or sid not in daily.index:
            continue
        daily.loc[sid, "pnl_net_1x"] += trade.get("pnl_net_1x", 0.0)
        daily.loc[sid, "pnl_net_1_5x"] += trade.get("pnl_net_1_5x", 0.0)
        daily.loc[sid, "pnl_net_2x"] += trade.get("pnl_net_2x", 0.0)

    return daily


# ---------------------------------------------------------------------------
# Métriques de performance (V1 §10)
# ---------------------------------------------------------------------------

def _sharpe(series: pd.Series) -> float:
    """Sharpe annualisé. std avec ddof=1 (sample std)."""
    s = series.std(ddof=1)
    if s == 0 or np.isnan(s):
        return 0.0
    return float(series.mean() / s * np.sqrt(252))


def compute_metrics(trades: list[dict], daily_pnl: pd.DataFrame) -> dict:
    """Calcule les métriques de performance V1 §10.

    Input:
        trades:    liste de tous les trades complétés
        daily_pnl: DataFrame (session_id index, 3 colonnes pnl_net)

    Output:
        dict avec toutes les métriques V1
    """
    # Sharpe sur chaque scénario
    sharpe_1x = _sharpe(daily_pnl["pnl_net_1x"])
    sharpe_1_5x = _sharpe(daily_pnl["pnl_net_1_5x"])
    sharpe_2x = _sharpe(daily_pnl["pnl_net_2x"])

    # Win Rate : TP / total trades complétés
    completed = [t for t in trades if t.get("exit_motif") is not None]
    n_total = len(completed)
    n_wins = sum(1 for t in completed if t["exit_motif"] == "TAKE_PROFIT")
    win_rate = n_wins / n_total if n_total > 0 else 0.0

    # Avg Win / Avg Loss (sur pnl_net_1x)
    tp_pnls = [t["pnl_net_1x"] for t in completed
               if t["exit_motif"] == "TAKE_PROFIT" and t.get("pnl_net_1x", 0) > 0]
    sl_pnls = [t["pnl_net_1x"] for t in completed
               if t["exit_motif"] == "STOP_LOSS" and t.get("pnl_net_1x", 0) < 0]
    avg_win = float(np.mean(tp_pnls)) if tp_pnls else 0.0
    avg_loss = float(abs(np.mean(sl_pnls))) if sl_pnls else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")

    # Max Drawdown — en dollars
    cumulative = daily_pnl["pnl_net_1x"].cumsum()
    rolling_max = cumulative.cummax()
    drawdown = cumulative - rolling_max
    max_dd_dollars = float(drawdown.min()) if len(drawdown) > 0 else 0.0
    # Pourcentage informatif — formule standard (dd / pic au moment du creux)
    dd_pct = drawdown / rolling_max.where(rolling_max > 0)
    max_dd_pct = float(dd_pct.min()) if dd_pct.notna().any() else 0.0

    # Fréquence sorties forcées
    n_forced = sum(1 for t in completed if t["exit_motif"] == "SORTIE_FORCEE")
    forced_rate = n_forced / n_total if n_total > 0 else 0.0

    # Fréquence SESSION_CLOSE
    n_session_close = sum(1 for t in completed if t["exit_motif"] == "SESSION_CLOSE")
    session_close_rate = n_session_close / n_total if n_total > 0 else 0.0

    # Slippage robustness
    slippage_robust = sharpe_1_5x > 0
    slippage_resilient = sharpe_2x > 0

    return {
        "sharpe_1x": sharpe_1x,
        "sharpe_1_5x": sharpe_1_5x,
        "sharpe_2x": sharpe_2x,
        "win_rate": win_rate,
        "n_wins": n_wins,
        "n_total": n_total,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "max_dd_dollars": max_dd_dollars,
        "max_dd_pct": max_dd_pct,
        "forced_rate": forced_rate,
        "session_close_rate": session_close_rate,
        "slippage_robust": slippage_robust,
        "slippage_resilient": slippage_resilient,
        "n_forced": n_forced,
        "n_session_close": n_session_close,
    }


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------

def run_backtest(df_a: pd.DataFrame, df_b: pd.DataFrame,
                 symbol_a: str, symbol_b: str,
                 pair_name: str,
                 verbose: bool = True) -> dict:
    """Boucle principale de backtest.

    Input:
        df_a, df_b:  DataFrames 5min complets (step1)
        symbol_a/b:  symboles des actifs
        pair_name:   clé dans PAIRS (ex: "GC_SI")
        verbose:     True = log par session, False = silencieux (tests)

    Output:
        dict avec pair, trades, daily_pnl, metrics, session_diagnostics, etc.
    """
    pair_config = PAIRS[pair_name]

    # Sessions communes
    sessions_a = set(df_a["session_id"].unique())
    sessions_b = set(df_b["session_id"].unique())
    all_sessions = sorted(sessions_a & sessions_b)

    # On commence à la 31ème session (30 pour calibration + 1 pour trading)
    tradeable_sessions = all_sessions[30:]

    all_trades: list[dict] = []
    session_diagnostics: list[dict] = []
    skip_reasons: dict[str, int] = {}
    n_traded = 0

    def log_skip(session_id: str, reason: str) -> None:
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
        if verbose:
            print(f"  SKIP {session_id}: {reason}")

    for target_session in tradeable_sessions:
        # 1. Fenêtre calibration
        calib = select_calibration_window(
            df_a, df_b, target_session, pair_config, n_sessions=30
        )
        if calib is None:
            log_skip(target_session, "insufficient_clean_sessions")
            continue
        df_a_calib, df_b_calib = calib

        # 2. Step 2 — Stationnarité
        # NOTE: avec 30 sessions, 60d = None → is_blocking ne se déclenche
        # effectivement jamais. Acceptable car I(1) est structurel pour CME.
        s2_a = run_step2(df_a_calib, symbol_a)
        s2_b = run_step2(df_b_calib, symbol_b)
        if s2_a["is_blocking"] or s2_b["is_blocking"]:
            log_skip(target_session, "stationarity_blocking")
            continue

        # 3. Step 3 — Cointégration
        s3 = run_step3(df_a_calib, df_b_calib, symbol_a, symbol_b)
        if s3["is_blocking"]:
            log_skip(target_session, "cointegration_blocking")
            continue

        # 4. Step 4 — Paramètres OU
        s4 = run_step4(s3, df_a_calib, df_b_calib)
        if s4["is_blocking"]:
            log_skip(target_session, "ou_blocking")
            continue

        # 5. Préparer session T
        df_session = prepare_session_df(df_a, df_b, target_session)
        if df_session is None or len(df_session) < 10:
            log_skip(target_session, "session_too_short")
            continue

        # 6. Step 5 — Exécution
        result = run_session(df_session, s4, pair_config)
        n_traded += 1

        # 7. PnL pour chaque trade
        for trade in result["trades"]:
            if trade["exit_timestamp"] is None:
                continue
            trade["pnl_brut"] = compute_pnl_brut(trade, s4)
            trade["cost_1x"] = compute_spread_cost_rt(trade, s4, 1.0)
            trade["cost_1_5x"] = compute_spread_cost_rt(trade, s4, 1.5)
            trade["cost_2x"] = compute_spread_cost_rt(trade, s4, 2.0)
            trade["pnl_net_1x"] = trade["pnl_brut"] - trade["cost_1x"]
            trade["pnl_net_1_5x"] = trade["pnl_brut"] - trade["cost_1_5x"]
            trade["pnl_net_2x"] = trade["pnl_brut"] - trade["cost_2x"]
            trade["session_id"] = target_session

        all_trades.extend(result["trades"])
        session_diagnostics.append({
            "session_id": target_session,
            **result["diagnostics"],
        })

        if verbose:
            n_calib = len(df_a_calib["session_id"].unique())
            print(f"=== SESSION {target_session} ===")
            print(f"  Calibration: {n_calib} sessions propres")
            print(f"  Step3: stat={s3['is_stationary_30d']}, "
                  f"beta={s3['beta_ols']:.4f}")
            print(f"  Step4: sigma_eq={s4['sigma_eq']:.6f}, "
                  f"HL_op={s4['hl_operational']:.0f}b")
            print(f"  Trades: {len(result['trades'])}")
            for t in result["trades"]:
                if t.get("pnl_brut") is not None:
                    print(f"    {t['direction']} | "
                          f"entry Z={t['entry_z']:.2f} | "
                          f"exit {t['exit_motif']} Z={t.get('exit_z', 0):.2f} | "
                          f"PnL_brut=${t['pnl_brut']:.0f} | "
                          f"net_1x=${t['pnl_net_1x']:.0f}")

    # Agrégation
    daily_pnl = aggregate_daily_pnl(all_trades, tradeable_sessions)
    metrics = compute_metrics(all_trades, daily_pnl)

    return {
        "pair": pair_name,
        "n_sessions_total": len(tradeable_sessions),
        "n_sessions_traded": n_traded,
        "n_sessions_skipped": len(tradeable_sessions) - n_traded,
        "skip_reasons": skip_reasons,
        "trades": all_trades,
        "daily_pnl": daily_pnl,
        "metrics": metrics,
        "session_diagnostics": session_diagnostics,
    }


if __name__ == "__main__":
    print("Backtester prêt. Usage :")
    print("  from src.backtester import run_backtest")
    print("  result = run_backtest(df_a, df_b, 'YM', 'RTY', 'YM_RTY')")
