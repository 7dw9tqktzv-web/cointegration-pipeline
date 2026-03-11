"""
Tests unitaires pour src/step2_stationarity.py.

Vérifie les invariants du V1 Section 5 :
- Downsampling session-aware (pas de cross-session)
- Nombre d'observations ~1000 après downsampling
- GC et SI sortent I(1) sur données réelles
- Correction BH appliquée
- Condition bloquante correcte
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.step1_data import run_step1
from src.step2_stationarity import (
    get_clean_sessions,
    select_window,
    downsample_session_aware,
    run_adf,
    run_kpss,
    classify_stationarity,
    apply_bh_correction,
    evaluate_multiscale,
    run_step2,
    WINDOW_CONFIG,
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
def df_gc():
    if not HAS_GC:
        pytest.skip("GC data not available")
    return run_step1(GC_FILE[0], "GC")


@pytest.fixture(scope="module")
def df_si():
    if not HAS_SI:
        pytest.skip("SI data not available")
    return run_step1(SI_FILE[0], "SI")


@pytest.fixture(scope="module")
def result_gc(df_gc):
    return run_step2(df_gc, "GC")


@pytest.fixture(scope="module")
def result_si(df_si):
    return run_step2(df_si, "SI")


# ---------------------------------------------------------------------------
# Tests — Downsampling
# ---------------------------------------------------------------------------

class TestDownsampling:
    """Vérifie le downsampling session-aware."""

    def test_no_cross_session_bars(self, df_gc):
        """Le downsampling ne crée pas de barres cross-session."""
        window = select_window(df_gc, 30)
        assert window is not None
        series = downsample_session_aware(window, 30)
        # Vérifier que les timestamps downsampleés sont dans les sessions
        # En reconstruisant session_id et vérifiant la monotonie
        idx = series.index
        dt = idx.to_series().diff().dropna()
        # Les grands écarts (> 2h) correspondent aux session breaks
        big_gaps = dt[dt > pd.Timedelta(hours=2)]
        # Aucun écart ne devrait être dans la dead zone 15:31–17:29
        for gap_ts in big_gaps.index:
            h = gap_ts.hour
            assert h >= 17 or h <= 15, \
                f"Barre cross-session détectée: {gap_ts}"

    def test_obs_count_30d_30min(self, df_gc):
        """30j downsampleé à 30min donne ~1000-1500 obs."""
        window = select_window(df_gc, 30)
        assert window is not None
        series = downsample_session_aware(window, 30)
        n = len(series)
        assert 500 < n < 2000, f"N={n} hors range attendu 500-2000"

    def test_obs_count_60d_60min(self, df_gc):
        """60j downsampleé à 60min donne ~1000-1500 obs."""
        window = select_window(df_gc, 60)
        assert window is not None
        series = downsample_session_aware(window, 60)
        n = len(series)
        assert 500 < n < 2000, f"N={n} hors range attendu 500-2000"

    def test_downsample_preserves_log_price_range(self, df_gc):
        """Le log-prix downsampleé reste dans le range du log-prix original."""
        window = select_window(df_gc, 30)
        assert window is not None
        original = np.log(window["price"])
        downsampled = downsample_session_aware(window, 30)
        assert downsampled.min() >= original.min() - 0.001
        assert downsampled.max() <= original.max() + 0.001


# ---------------------------------------------------------------------------
# Tests — Classification stationnarité
# ---------------------------------------------------------------------------

class TestClassification:
    """Vérifie la matrice ADF x KPSS (Table 5)."""

    def test_i1_case(self):
        """ADF non-rejet + KPSS rejet → I(1)."""
        assert classify_stationarity(0.50, 0.01) == "I(1)"

    def test_i0_case(self):
        """ADF rejet + KPSS non-rejet → I(0)."""
        assert classify_stationarity(0.01, 0.50) == "I(0)"

    def test_inconsistent_case(self):
        """Les deux rejettent → inconsistent."""
        assert classify_stationarity(0.01, 0.01) == "inconsistent"

    def test_ambiguous_case(self):
        """Aucun ne rejette → ambiguous."""
        assert classify_stationarity(0.50, 0.50) == "ambiguous"


# ---------------------------------------------------------------------------
# Tests — Sessions propres
# ---------------------------------------------------------------------------

class TestCleanSessions:
    """Vérifie la sélection de sessions propres."""

    def test_excludes_low_liquidity(self, df_gc):
        """Les sessions low_liquidity sont exclues."""
        clean = get_clean_sessions(df_gc)
        low_liq = df_gc[df_gc["low_liquidity_day"]]["session_id"].unique()
        for sid in low_liq:
            assert sid not in clean

    def test_select_window_count(self, df_gc):
        """select_window retourne le bon nombre de sessions."""
        window = select_window(df_gc, 10)
        assert window is not None
        n = window["session_id"].nunique()
        assert n == 10

    def test_select_window_none_if_insufficient(self, df_gc):
        """select_window retourne None si pas assez de sessions."""
        result = select_window(df_gc, 9999)
        assert result is None


# ---------------------------------------------------------------------------
# Tests — Résultats sur données réelles
# ---------------------------------------------------------------------------

class TestRealData:
    """Vérifie que GC et SI sortent I(1) sur les données réelles."""

    def test_gc_is_i1(self, result_gc):
        """GC doit être I(1)."""
        assert result_gc["is_I1"] is True

    def test_gc_not_blocking(self, result_gc):
        """GC ne doit pas être bloquant."""
        assert result_gc["is_blocking"] is False

    def test_si_is_i1(self, result_si):
        """SI doit être I(1)."""
        assert result_si["is_I1"] is True

    def test_si_not_blocking(self, result_si):
        """SI ne doit pas être bloquant."""
        assert result_si["is_blocking"] is False

    def test_bh_correction_applied(self, result_gc):
        """Les p-values ajustées BH sont présentes."""
        for wname, wdata in result_gc["windows"].items():
            if wdata is None:
                continue
            for freq, fdata in wdata["freqs"].items():
                assert "pvalue_adj" in fdata["adf"], \
                    f"{wname}/{freq}min: pvalue_adj manquant pour ADF"
                assert "pvalue_adj" in fdata["kpss"], \
                    f"{wname}/{freq}min: pvalue_adj manquant pour KPSS"

    def test_bh_pvalues_geq_raw(self, result_gc):
        """Les p-values ajustées BH sont >= p-values brutes."""
        for wname, wdata in result_gc["windows"].items():
            if wdata is None:
                continue
            for freq, fdata in wdata["freqs"].items():
                for test in ["adf", "kpss"]:
                    raw = fdata[test]["pvalue"]
                    adj = fdata[test]["pvalue_adj"]
                    assert adj >= raw - 1e-10, \
                        f"{wname}/{freq}min/{test}: adj={adj} < raw={raw}"

    def test_all_windows_have_results(self, result_gc):
        """Les 3 fenêtres (10d, 30d, 60d) ont des résultats."""
        for wname in ["10d", "30d", "60d"]:
            assert result_gc["windows"].get(wname) is not None, \
                f"Fenêtre {wname} manquante"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
