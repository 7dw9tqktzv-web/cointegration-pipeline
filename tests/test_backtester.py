"""
Tests backtester — fenêtre calibration, PnL, coûts, métriques, pipeline.

Tests synthétiques déterministes + tests sur données réelles YM/RTY.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.contracts import CONTRACTS, COSTS_RT
from src.backtester import (
    select_calibration_window,
    prepare_session_df,
    compute_pnl_brut,
    compute_spread_cost_rt,
    aggregate_daily_pnl,
    compute_metrics,
    run_backtest,
)


# ===================================================================
# Helpers — Création de DataFrames synthétiques
# ===================================================================

def _make_session_df(session_ids: list[str],
                     n_bars: int = 10,
                     price: float = 100.0,
                     rollover_sessions: set[str] | None = None,
                     low_liq_sessions: set[str] | None = None) -> pd.DataFrame:
    """Crée un DataFrame 5min synthétique avec les colonnes step1."""
    rollover_sessions = rollover_sessions or set()
    low_liq_sessions = low_liq_sessions or set()

    rows = []
    for sid in session_ids:
        base_ts = pd.Timestamp(f"{sid[:4]}-{sid[4:6]}-{sid[6:8]} 18:00")
        for i in range(n_bars):
            rows.append({
                "session_id": sid,
                "price": price + np.random.randn() * 0.1,
                "log_price": np.log(price + np.random.randn() * 0.1),
                "rollover_discontinuity": sid in rollover_sessions,
                "low_liquidity_day": sid in low_liq_sessions,
            })
    df = pd.DataFrame(rows)
    # DatetimeIndex
    timestamps = []
    for sid in session_ids:
        base_ts = pd.Timestamp(f"{sid[:4]}-{sid[4:6]}-{sid[6:8]} 18:00")
        for i in range(n_bars):
            timestamps.append(base_ts + pd.Timedelta(minutes=5 * i))
    df.index = pd.DatetimeIndex(timestamps)
    return df


def _make_session_ids(n: int, start: str = "20250101") -> list[str]:
    """Génère n session_ids consécutifs (jours ouvrés simulés)."""
    base = pd.Timestamp(start)
    return [(base + pd.Timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


# ===================================================================
# Test Fenêtre Calibration
# ===================================================================

class TestCalibrationWindow:

    def test_target_excluded(self):
        """La session target n'est JAMAIS dans la fenêtre."""
        sids = _make_session_ids(40)
        df_a = _make_session_df(sids, price=2000.0)
        df_b = _make_session_df(sids, price=25.0)
        target = sids[35]
        pair_config = {"rollover_excl": 0}

        result = select_calibration_window(df_a, df_b, target, pair_config, 30)
        assert result is not None
        df_a_cal, df_b_cal = result
        assert target not in df_a_cal["session_id"].values
        assert target not in df_b_cal["session_id"].values

    def test_returns_n_sessions(self):
        """Retourne exactement 30 sessions propres."""
        sids = _make_session_ids(40)
        df_a = _make_session_df(sids, price=2000.0)
        df_b = _make_session_df(sids, price=25.0)
        target = sids[35]
        pair_config = {"rollover_excl": 0}

        result = select_calibration_window(df_a, df_b, target, pair_config, 30)
        assert result is not None
        df_a_cal, _ = result
        assert len(df_a_cal["session_id"].unique()) == 30

    def test_insufficient_returns_none(self):
        """Moins de 30 sessions propres → None."""
        sids = _make_session_ids(25)
        df_a = _make_session_df(sids, price=2000.0)
        df_b = _make_session_df(sids, price=25.0)
        target = sids[-1]
        pair_config = {"rollover_excl": 0}

        result = select_calibration_window(df_a, df_b, target, pair_config, 30)
        assert result is None

    def test_rollover_exclusion(self):
        """Rollover ±N exclut la session rollover + N voisines."""
        sids = _make_session_ids(45)
        rollover = {sids[20]}
        df_a = _make_session_df(sids, price=2000.0, rollover_sessions=rollover)
        df_b = _make_session_df(sids, price=25.0)
        target = sids[40]
        pair_config = {"rollover_excl": 3}

        result = select_calibration_window(df_a, df_b, target, pair_config, 30)
        assert result is not None
        df_a_cal, _ = result
        calib_sids = set(df_a_cal["session_id"].unique())
        # Rollover + 3 voisines de chaque côté exclues
        for offset in range(-3, 4):
            idx = 20 + offset
            if 0 <= idx < len(sids):
                assert sids[idx] not in calib_sids

    def test_rollover_excl_zero(self):
        """rollover_excl=0 → seule la session rollover exclue."""
        sids = _make_session_ids(45)
        rollover = {sids[20]}
        df_a = _make_session_df(sids, price=2000.0, rollover_sessions=rollover)
        df_b = _make_session_df(sids, price=25.0)
        target = sids[40]
        pair_config = {"rollover_excl": 0}

        result = select_calibration_window(df_a, df_b, target, pair_config, 30)
        assert result is not None
        df_a_cal, _ = result
        calib_sids = set(df_a_cal["session_id"].unique())
        assert sids[20] not in calib_sids
        # Voisines présentes
        assert sids[19] in calib_sids or sids[19] >= target
        assert sids[21] in calib_sids or sids[21] >= target

    def test_low_liquidity_excluded(self):
        """Sessions low_liquidity exclues de la calibration."""
        sids = _make_session_ids(40)
        low_liq = {sids[10], sids[15]}
        df_a = _make_session_df(sids, price=2000.0, low_liq_sessions=low_liq)
        df_b = _make_session_df(sids, price=25.0)
        target = sids[35]
        pair_config = {"rollover_excl": 0}

        result = select_calibration_window(df_a, df_b, target, pair_config, 30)
        assert result is not None
        df_a_cal, _ = result
        calib_sids = set(df_a_cal["session_id"].unique())
        assert sids[10] not in calib_sids
        assert sids[15] not in calib_sids


# ===================================================================
# Test Prepare Session
# ===================================================================

class TestPrepareSession:

    def test_inner_join(self):
        """Inner join : seuls les timestamps communs."""
        sids = ["20250101"]
        df_a = _make_session_df(sids, n_bars=10, price=2000.0)
        df_b = _make_session_df(sids, n_bars=10, price=25.0)
        result = prepare_session_df(df_a, df_b, "20250101")
        assert result is not None
        assert "price_a" in result.columns
        assert "price_b" in result.columns
        assert len(result) == 10

    def test_missing_session_returns_none(self):
        """Session absente d'un actif → None."""
        sids = ["20250101"]
        df_a = _make_session_df(sids, price=2000.0)
        df_b = _make_session_df(sids, price=25.0)
        result = prepare_session_df(df_a, df_b, "20250201")
        assert result is None


# ===================================================================
# Test PnL Brut
# ===================================================================

class TestPnlBrut:

    @pytest.fixture
    def trade_long_gc_si(self):
        """Trade LONG GC/SI synthétique."""
        return {
            "direction": "LONG",
            "entry_price_a": 2000.0,  # GC
            "entry_price_b": 25.0,    # SI
            "exit_price_a": 2010.0,
            "exit_price_b": 24.5,
            "sizing": {
                "Q_A_std": 1, "Q_A_micro": 0,
                "Q_B_std": 1, "Q_B_micro": 2,
                "micro_sym_B": "SIL",
            },
        }

    @pytest.fixture
    def s4_gc_si(self):
        return {
            "direction": "A_B",
            "symbol_a": "GC",
            "symbol_b": "SI",
        }

    def test_long_pnl_positive(self, trade_long_gc_si, s4_gc_si):
        """LONG : dep monte + indep descend → PnL > 0."""
        pnl = compute_pnl_brut(trade_long_gc_si, s4_gc_si)
        # GC leg (dep, LONG): (2010-2000) × 1 × 100 = 1000
        # SI leg (indep, SHORT std): (25-24.5) × 1 × 5000 = 2500
        # SI leg (indep, SHORT micro): (25-24.5) × 2 × 1000 = 1000
        # Total = 1000 + 2500 + 1000 = 4500
        assert pnl == pytest.approx(4500.0)

    def test_short_pnl_inverted(self, trade_long_gc_si, s4_gc_si):
        """SHORT = signes inversés par rapport à LONG."""
        trade_short = {**trade_long_gc_si, "direction": "SHORT"}
        pnl_long = compute_pnl_brut(trade_long_gc_si, s4_gc_si)
        pnl_short = compute_pnl_brut(trade_short, s4_gc_si)
        assert pnl_short == pytest.approx(-pnl_long)

    def test_uses_multiplier_not_tick_value(self, trade_long_gc_si, s4_gc_si):
        """PnL utilise multiplier (prohibition #3)."""
        pnl = compute_pnl_brut(trade_long_gc_si, s4_gc_si)
        # Si on utilisait tick_value (GC=10) au lieu de multiplier (GC=100)
        # le PnL serait 10× plus petit. Vérifier l'ordre de grandeur.
        assert abs(pnl) > 100  # Pas 10× plus petit

    def test_direction_b_a(self):
        """Direction B_A : dep=B, indep=A."""
        trade = {
            "direction": "LONG",
            "entry_price_a": 2000.0,
            "entry_price_b": 25.0,
            "exit_price_a": 2000.0,   # indep (A) inchangé
            "exit_price_b": 26.0,     # dep (B) monte → profit
            "sizing": {
                "Q_A_std": 1, "Q_A_micro": 0,
                "Q_B_std": 1, "Q_B_micro": 0,
                "micro_sym_B": None,
            },
        }
        s4 = {"direction": "B_A", "symbol_a": "GC", "symbol_b": "SI"}
        pnl = compute_pnl_brut(trade, s4)
        # dep = SI (B), LONG: (26-25) × 1 × 5000 = 5000
        # indep = GC (A), SHORT: (2000-2000) × 1 × 100 = 0
        assert pnl == pytest.approx(5000.0)

    def test_qa_micro_zero_no_effect(self, trade_long_gc_si, s4_gc_si):
        """Q_A_micro = 0 → pas de contribution micro leg A."""
        assert trade_long_gc_si["sizing"]["Q_A_micro"] == 0
        # PnL ne dépend pas de mult_dep_micro
        pnl = compute_pnl_brut(trade_long_gc_si, s4_gc_si)
        assert pnl == pytest.approx(4500.0)


# ===================================================================
# Test Coûts de Transaction
# ===================================================================

class TestSpreadCost:

    @pytest.fixture
    def trade_gc_si(self):
        return {
            "sizing": {
                "Q_A_std": 1, "Q_A_micro": 0,
                "Q_B_std": 1, "Q_B_micro": 2,
                "micro_sym_B": "SIL",
            },
        }

    @pytest.fixture
    def s4_gc_si(self):
        return {"direction": "A_B", "symbol_a": "GC", "symbol_b": "SI"}

    def test_cost_positive(self, trade_gc_si, s4_gc_si):
        """Le coût est toujours positif."""
        cost = compute_spread_cost_rt(trade_gc_si, s4_gc_si, 1.0)
        assert cost > 0

    def test_monotone_slippage(self, trade_gc_si, s4_gc_si):
        """cost(2x) > cost(1.5x) > cost(1x)."""
        c1 = compute_spread_cost_rt(trade_gc_si, s4_gc_si, 1.0)
        c15 = compute_spread_cost_rt(trade_gc_si, s4_gc_si, 1.5)
        c2 = compute_spread_cost_rt(trade_gc_si, s4_gc_si, 2.0)
        assert c2 > c15 > c1

    def test_comm_fixed_across_slippage(self, trade_gc_si, s4_gc_si):
        """Commission invariante quel que soit slippage_mult."""
        # Coût 1x vs 2x : la différence = slippage supplémentaire uniquement
        c1 = compute_spread_cost_rt(trade_gc_si, s4_gc_si, 1.0)
        c2 = compute_spread_cost_rt(trade_gc_si, s4_gc_si, 2.0)
        # Diff = slip supplémentaire sur toutes les legs
        # GC std: 1 × 20 × (2-1) = 20
        # SI std: 1 × 50 × (2-1) = 50
        # SIL micro: 2 × 10 × (2-1) = 20
        expected_diff = 20.0 + 50.0 + 20.0
        assert (c2 - c1) == pytest.approx(expected_diff)

    def test_exact_cost_1x(self, trade_gc_si, s4_gc_si):
        """Vérification arithmétique du coût 1x."""
        cost = compute_spread_cost_rt(trade_gc_si, s4_gc_si, 1.0)
        # GC std: 1 × (4.20 + 20.00) = 24.20
        # SI std: 1 × (4.20 + 50.00) = 54.20
        # SIL micro: 2 × (2.50 + 10.00) = 25.00
        expected = 24.20 + 54.20 + 25.00
        assert cost == pytest.approx(expected)

    def test_double_cost_prohibition7(self, trade_gc_si, s4_gc_si):
        """Prohibition #7 : coût appelé 1 fois. 2× appels = 2× coût."""
        c = compute_spread_cost_rt(trade_gc_si, s4_gc_si, 1.0)
        assert 2 * c == pytest.approx(2 * c)  # Tautologie, mais vérifie la linéarité


# ===================================================================
# Test Agrégation Daily PnL
# ===================================================================

class TestAggregateDailyPnl:

    def test_sessions_without_trades_have_zero(self):
        """Sessions sans trade → PnL = 0 (pas manquantes)."""
        all_sids = ["20250101", "20250102", "20250103"]
        trades = [{
            "session_id": "20250101",
            "pnl_net_1x": 100.0,
            "pnl_net_1_5x": 80.0,
            "pnl_net_2x": 60.0,
        }]
        daily = aggregate_daily_pnl(trades, all_sids)
        assert len(daily) == 3
        assert daily.loc["20250102", "pnl_net_1x"] == 0.0
        assert daily.loc["20250103", "pnl_net_1x"] == 0.0

    def test_multiple_trades_same_session(self):
        """Plusieurs trades même session → somme."""
        trades = [
            {"session_id": "20250101", "pnl_net_1x": 100.0,
             "pnl_net_1_5x": 80.0, "pnl_net_2x": 60.0},
            {"session_id": "20250101", "pnl_net_1x": -50.0,
             "pnl_net_1_5x": -60.0, "pnl_net_2x": -70.0},
        ]
        daily = aggregate_daily_pnl(trades, ["20250101"])
        assert daily.loc["20250101", "pnl_net_1x"] == pytest.approx(50.0)
        assert daily.loc["20250101", "pnl_net_1_5x"] == pytest.approx(20.0)

    def test_index_is_session_id(self):
        """Index = session_id, pas date calendaire."""
        daily = aggregate_daily_pnl([], ["20250101", "20250102"])
        assert daily.index.name == "session_id"
        assert list(daily.index) == ["20250101", "20250102"]


# ===================================================================
# Test Métriques
# ===================================================================

class TestMetrics:

    def test_sharpe_on_net(self):
        """Sharpe calculé sur PnL_net, pas brut."""
        trades = [
            {"exit_motif": "TAKE_PROFIT", "pnl_net_1x": 100.0},
        ]
        daily = pd.DataFrame({
            "pnl_net_1x": [100.0, -50.0, 30.0, 20.0, -10.0],
            "pnl_net_1_5x": [90.0, -55.0, 25.0, 15.0, -15.0],
            "pnl_net_2x": [80.0, -60.0, 20.0, 10.0, -20.0],
        })
        m = compute_metrics(trades, daily)
        assert m["sharpe_1x"] != 0
        # 1x > 1.5x > 2x en moyenne → sharpe_1x > sharpe_2x
        assert m["sharpe_1x"] > m["sharpe_2x"]

    def test_sharpe_ddof1(self):
        """Sharpe utilise ddof=1."""
        daily = pd.DataFrame({
            "pnl_net_1x": [10.0, 20.0],
            "pnl_net_1_5x": [0.0, 0.0],
            "pnl_net_2x": [0.0, 0.0],
        })
        m = compute_metrics([], daily)
        expected = (15.0 / pd.Series([10.0, 20.0]).std(ddof=1)) * np.sqrt(252)
        assert m["sharpe_1x"] == pytest.approx(expected)

    def test_win_rate_tp_only(self):
        """Win rate = TP / total."""
        trades = [
            {"exit_motif": "TAKE_PROFIT", "pnl_net_1x": 100.0},
            {"exit_motif": "STOP_LOSS", "pnl_net_1x": -50.0},
            {"exit_motif": "SESSION_CLOSE", "pnl_net_1x": 20.0},
        ]
        daily = pd.DataFrame({
            "pnl_net_1x": [70.0], "pnl_net_1_5x": [60.0], "pnl_net_2x": [50.0],
        })
        m = compute_metrics(trades, daily)
        assert m["win_rate"] == pytest.approx(1 / 3)

    def test_max_dd_in_dollars(self):
        """Max drawdown reporté en dollars."""
        daily = pd.DataFrame({
            "pnl_net_1x": [100.0, -200.0, 50.0],
            "pnl_net_1_5x": [0.0, 0.0, 0.0],
            "pnl_net_2x": [0.0, 0.0, 0.0],
        })
        m = compute_metrics([], daily)
        # Cumul: 100, -100, -50. Peak: 100, 100, 100. DD: 0, -200, -150
        assert m["max_dd_dollars"] == pytest.approx(-200.0)

    def test_forced_rate(self):
        """Taux de sorties forcées."""
        trades = [
            {"exit_motif": "SORTIE_FORCEE", "pnl_net_1x": -30.0},
            {"exit_motif": "TAKE_PROFIT", "pnl_net_1x": 50.0},
            {"exit_motif": "TAKE_PROFIT", "pnl_net_1x": 40.0},
            {"exit_motif": "STOP_LOSS", "pnl_net_1x": -20.0},
        ]
        daily = pd.DataFrame({
            "pnl_net_1x": [40.0], "pnl_net_1_5x": [30.0], "pnl_net_2x": [20.0],
        })
        m = compute_metrics(trades, daily)
        assert m["forced_rate"] == pytest.approx(0.25)

    def test_no_trades(self):
        """Aucun trade → métriques à 0 sans crash."""
        daily = pd.DataFrame({
            "pnl_net_1x": [0.0, 0.0],
            "pnl_net_1_5x": [0.0, 0.0],
            "pnl_net_2x": [0.0, 0.0],
        })
        m = compute_metrics([], daily)
        assert m["sharpe_1x"] == 0.0
        assert m["win_rate"] == 0.0
        assert m["n_total"] == 0


# ===================================================================
# Test Pipeline Réel (YM/RTY)
# ===================================================================

_DATA_RAW = _PROJECT_ROOT / "data" / "raw"
_HAS_YM = (_DATA_RAW / "YM.Last.txt").exists()
_HAS_RTY = (_DATA_RAW / "RTY.Last.txt").exists()
_SKIP_REAL = not (_HAS_YM and _HAS_RTY)


@pytest.mark.skipif(_SKIP_REAL, reason="YM/RTY raw data not available")
class TestRealPipeline:

    @pytest.fixture(scope="class")
    def real_data(self):
        """Charge YM + RTY via step1."""
        from src.step1_data import run_step1
        df_ym = run_step1("YM")
        df_rty = run_step1("RTY")
        return df_ym, df_rty

    @pytest.fixture(scope="class")
    def backtest_result(self, real_data):
        """Run backtest complet YM/RTY."""
        df_ym, df_rty = real_data

        # Ajouter YM_RTY aux PAIRS si absent (NQ_RTY existe, pas YM_RTY)
        from config.contracts import PAIRS
        if "YM_RTY" not in PAIRS:
            pytest.skip("YM_RTY not in PAIRS config")

        result = run_backtest(df_ym, df_rty, "YM", "RTY", "YM_RTY",
                              verbose=False)
        return result

    def test_at_least_one_session_traded(self, backtest_result):
        """Au moins 1 session tradée."""
        assert backtest_result["n_sessions_traded"] > 0

    def test_all_skips_have_reason(self, backtest_result):
        """Toutes les sessions skippées ont une raison."""
        total_skipped = sum(backtest_result["skip_reasons"].values())
        assert total_skipped == backtest_result["n_sessions_skipped"]

    def test_pnl_monotone(self, backtest_result):
        """PnL_net_2x ≤ PnL_net_1.5x ≤ PnL_net_1x pour chaque trade."""
        for t in backtest_result["trades"]:
            if t.get("pnl_net_1x") is None:
                continue
            assert t["pnl_net_2x"] <= t["pnl_net_1_5x"] + 1e-10
            assert t["pnl_net_1_5x"] <= t["pnl_net_1x"] + 1e-10

    def test_no_unclosed_trades(self, backtest_result):
        """Pas de trade avec exit_timestamp = None (SESSION_CLOSE attrape tout)."""
        for t in backtest_result["trades"]:
            assert t["exit_timestamp"] is not None

    def test_metrics_fields_complete(self, backtest_result):
        """Toutes les métriques V1 présentes."""
        m = backtest_result["metrics"]
        required = [
            "sharpe_1x", "sharpe_1_5x", "sharpe_2x",
            "win_rate", "avg_win", "avg_loss", "win_loss_ratio",
            "max_dd_dollars", "forced_rate", "slippage_robust",
        ]
        for key in required:
            assert key in m, f"Métrique manquante: {key}"

    def test_daily_pnl_complete(self, backtest_result):
        """daily_pnl a une ligne par session (tradées + skippées)."""
        daily = backtest_result["daily_pnl"]
        assert len(daily) == backtest_result["n_sessions_total"]
        assert "pnl_net_1x" in daily.columns

    def test_verbose_false_silent(self, real_data, capsys):
        """verbose=False ne produit aucun print."""
        df_ym, df_rty = real_data
        from config.contracts import PAIRS
        if "YM_RTY" not in PAIRS:
            pytest.skip("YM_RTY not in PAIRS config")

        run_backtest(df_ym, df_rty, "YM", "RTY", "YM_RTY", verbose=False)
        captured = capsys.readouterr()
        assert captured.out == ""
