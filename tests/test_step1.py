"""
Tests unitaires pour src/step1_data.py.

Vérifie les invariants critiques du V1 :
- Pas de barres cross-session (interdit #1)
- session_break → log_return = NaN
- Pas de barres en dead zone (15:31–17:29)
- session_id = date de clôture (lendemain pour barres du soir)
- Agrégation 5min correcte
- Price type correctement appliqué
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.step1_data import (
    load_sierra_csv,
    assign_sessions,
    flag_duplicates,
    flag_gaps,
    compute_log_returns,
    flag_rollover_discontinuity,
    flag_outliers,
    flag_low_liquidity_days,
    compute_price,
    aggregate_5min,
    run_step1,
)

DATA_DIR = PROJECT_ROOT / "data" / "raw"
GC_FILE = list(DATA_DIR.glob("GC*"))
SI_FILE = list(DATA_DIR.glob("SI*"))

HAS_GC = len(GC_FILE) > 0
HAS_SI = len(SI_FILE) > 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def df_gc_5min():
    """DataFrame 5min GC complet."""
    if not HAS_GC:
        pytest.skip("GC data not available")
    return run_step1(GC_FILE[0], "GC")


@pytest.fixture(scope="module")
def df_si_5min():
    """DataFrame 5min SI complet."""
    if not HAS_SI:
        pytest.skip("SI data not available")
    return run_step1(SI_FILE[0], "SI")


# ---------------------------------------------------------------------------
# Tests critiques — Les invariants du V1
# ---------------------------------------------------------------------------

class TestSessionAssignment:
    """Vérifie le découpage en sessions CME."""

    def test_no_dead_zone_bars(self, df_gc_5min):
        """Aucune barre entre 15:31 et 17:29 CT."""
        time_min = df_gc_5min.index.hour * 60 + df_gc_5min.index.minute
        dead = (time_min > 930) & (time_min < 1050)
        assert dead.sum() == 0, f"{dead.sum()} barres en dead zone"

    def test_session_break_has_nan_log_return(self, df_gc_5min):
        """RÈGLE ABSOLUE : log_return = NaN sur session_break."""
        breaks = df_gc_5min[df_gc_5min["session_break"]]
        assert breaks["log_return"].isna().all(), \
            "log_return non-NaN trouvé sur session_break"

    def test_session_id_format(self, df_gc_5min):
        """session_id au format YYYYMMDD."""
        sids = df_gc_5min["session_id"].unique()
        for sid in sids:
            assert len(sid) == 8 and sid.isdigit(), f"session_id invalide: {sid}"

    def test_evening_bar_session_id_is_next_day(self, df_gc_5min):
        """Barre 17:30 du soir → session_id = lendemain."""
        evening_bars = df_gc_5min[df_gc_5min.index.hour >= 17]
        if len(evening_bars) == 0:
            pytest.skip("Pas de barres du soir")
        for ts, row in evening_bars.head(5).iterrows():
            expected_date = (ts + pd.Timedelta(days=1)).strftime("%Y%m%d")
            assert row["session_id"] == expected_date, \
                f"Bar {ts} devrait avoir session_id={expected_date}, a {row['session_id']}"

    def test_no_cross_session_log_return(self, df_gc_5min):
        """Aucun log_return ne traverse une frontière de session."""
        # Les barres juste après un session_break doivent avoir NaN
        breaks = df_gc_5min[df_gc_5min["session_break"]]
        non_nan = breaks["log_return"].dropna()
        assert len(non_nan) == 0, \
            f"{len(non_nan)} log_return non-NaN traversent une session"


class TestAggregation:
    """Vérifie l'agrégation 1min → 5min."""

    def test_5min_alignment(self, df_gc_5min):
        """Les barres sont alignées sur des multiples de 5min."""
        # Chaque barre doit commencer à un multiple de 5min (xx:00, xx:05, etc.)
        minutes = df_gc_5min.index.minute
        assert (minutes % 5 == 0).all(), \
            f"Barres non-alignées: {minutes[minutes % 5 != 0].unique()}"

    def test_5min_spacing_within_session(self, df_gc_5min):
        """Dans une session, les écarts sont des multiples de 5min."""
        for sid, group in list(df_gc_5min.groupby("session_id"))[:5]:
            dt = group.index.to_series().diff().dropna()
            # Tous les écarts doivent être des multiples de 5min
            remainder = dt % pd.Timedelta(minutes=5)
            bad = remainder[remainder != pd.Timedelta(0)]
            assert len(bad) == 0, \
                f"Session {sid}: écarts non-multiples de 5min: {bad}"

    def test_volume_positive(self, df_gc_5min):
        """Le volume est toujours positif."""
        assert (df_gc_5min["volume"] > 0).all()

    def test_ohlc_consistency(self, df_gc_5min):
        """high >= max(open, close) et low <= min(open, close)."""
        assert (df_gc_5min["high"] >= df_gc_5min["open"]).all()
        assert (df_gc_5min["high"] >= df_gc_5min["close"]).all()
        assert (df_gc_5min["low"] <= df_gc_5min["open"]).all()
        assert (df_gc_5min["low"] <= df_gc_5min["close"]).all()


class TestPriceType:
    """Vérifie le calcul du price type."""

    def test_gc_price_is_close(self, df_gc_5min):
        """GC (liquide) → price = close."""
        assert (df_gc_5min["price"] == df_gc_5min["close"]).all()

    def test_si_price_is_typical(self, df_si_5min):
        """SI (moins liquide) → price = (H+L+C)/3."""
        expected = (df_si_5min["high"] + df_si_5min["low"]
                    + df_si_5min["close"]) / 3
        np.testing.assert_allclose(
            df_si_5min["price"].values, expected.values, rtol=1e-10
        )


class TestFlags:
    """Vérifie les flags de qualité."""

    def test_flags_are_boolean(self, df_gc_5min):
        """Tous les flags sont booléens."""
        for flag in ["gap_detected", "outlier", "rollover_discontinuity",
                     "low_liquidity_day", "session_break"]:
            assert df_gc_5min[flag].dtype == bool, f"{flag} n'est pas bool"

    def test_flagged_bars_have_nan_log_return(self, df_gc_5min):
        """Les barres flaggées (gap, outlier, rollover) ont log_return = NaN."""
        for flag in ["gap_detected", "outlier", "rollover_discontinuity"]:
            flagged = df_gc_5min[df_gc_5min[flag]]
            if len(flagged) > 0:
                assert flagged["log_return"].isna().all(), \
                    f"log_return non-NaN trouvé sur {flag}"

    def test_low_liquidity_is_session_wide(self, df_gc_5min):
        """low_liquidity_day est constant au sein d'une session."""
        for sid, group in df_gc_5min.groupby("session_id"):
            vals = group["low_liquidity_day"].unique()
            assert len(vals) == 1, \
                f"Session {sid}: low_liquidity_day non constant"


class TestLogReturns:
    """Vérifie les log_returns."""

    def test_log_return_range(self, df_gc_5min):
        """Les log_returns valides sont dans un range raisonnable (< 5%)."""
        valid = df_gc_5min["log_return"].dropna()
        assert valid.abs().max() < 0.05, \
            f"log_return extrême: {valid.abs().max():.4f}"

    def test_log_return_mean_near_zero(self, df_gc_5min):
        """La moyenne des log_returns est proche de zéro."""
        valid = df_gc_5min["log_return"].dropna()
        assert abs(valid.mean()) < 0.001, \
            f"Moyenne log_return anormale: {valid.mean():.6f}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
