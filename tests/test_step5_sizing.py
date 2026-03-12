"""
Tests step5_sizing — Phase 5 sizing beta-neutral.

Tests déterministes : pas de données aléatoires.
"""

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.step5_sizing import compute_sizing, _find_micro, MICRO_MAP
from config.contracts import CONTRACTS


# ===================================================================
# TestMicroMap
# ===================================================================

class TestMicroMap:

    def test_gc_has_micro(self):
        assert _find_micro("GC") == "MGC"

    def test_si_has_sil(self):
        assert _find_micro("SI") == "SIL"

    def test_nq_has_mnq(self):
        assert _find_micro("NQ") == "MNQ"

    def test_rty_has_m2k(self):
        assert _find_micro("RTY") == "M2K"

    def test_ng_has_qg(self):
        assert _find_micro("NG") == "QG"

    def test_ho_no_micro(self):
        assert _find_micro("HO") is None

    def test_rb_no_micro(self):
        assert _find_micro("RB") is None

    def test_pa_no_micro(self):
        assert _find_micro("PA") is None

    def test_unknown_symbol(self):
        assert _find_micro("UNKNOWN") is None


# ===================================================================
# TestSizingGCSI — GC/SI avec micro SIL
# ===================================================================

class TestSizingGCSI:

    @pytest.fixture
    def gc_si(self):
        bar = {
            "raw_price_a": 2000.0,  # GC
            "raw_price_b": 25.0,    # SI
            "beta_kalman": 1.0,
        }
        s4 = {"direction": "A_B", "symbol_a": "GC", "symbol_b": "SI"}
        return compute_sizing(bar, s4)

    def test_is_valid(self, gc_si):
        assert gc_si["is_valid"]

    def test_notional_a_uses_multiplier(self, gc_si):
        """notional_A = 2000 * 1 * 100 (GC multiplier) = 200_000."""
        expected = 2000.0 * 1 * CONTRACTS["GC"]["multiplier"]
        assert gc_si["notional_A"] == expected

    def test_target_notional_b(self, gc_si):
        """target = notional_A * |beta| = 200_000."""
        assert gc_si["target_notional_B"] == gc_si["notional_A"] * 1.0

    def test_sizing_decomposition(self, gc_si):
        """SI mult=5000, SIL mult=1000, ratio=5.

        target = 200_000, price_b = 25.0
        Q_total_micros = 200000 / (25 * 1000) = 8.0 → 8
        Q_B_std = 8 // 5 = 1
        Q_B_micro = 8 % 5 = 3
        actual = (1*5000 + 3*1000) * 25 = 200_000
        """
        assert gc_si["Q_B_std"] == 1
        assert gc_si["Q_B_micro"] == 3
        assert gc_si["micro_sym_B"] == "SIL"

    def test_residual_zero_exact(self, gc_si):
        """Cas exact : résidu = 0."""
        assert abs(gc_si["residual"]) < 0.01

    def test_multiplier_not_tick_value(self, gc_si):
        """Vérifie que notional utilise multiplier (100), pas tick_value (10)."""
        # Si on utilisait tick_value par erreur : 2000 * 10 = 20_000
        assert gc_si["notional_A"] == 200_000.0


# ===================================================================
# TestSizingNQRTY — NQ/RTY avec micro M2K
# ===================================================================

class TestSizingNQRTY:

    @pytest.fixture
    def nq_rty(self):
        bar = {
            "raw_price_a": 20000.0,  # NQ
            "raw_price_b": 2200.0,   # RTY
            "beta_kalman": 1.07,
        }
        s4 = {"direction": "A_B", "symbol_a": "NQ", "symbol_b": "RTY"}
        return compute_sizing(bar, s4)

    def test_is_valid(self, nq_rty):
        assert nq_rty["is_valid"]

    def test_notional_a(self, nq_rty):
        expected = 20000.0 * 1 * CONTRACTS["NQ"]["multiplier"]  # 20000*20=400000
        assert nq_rty["notional_A"] == expected

    def test_micro_sym(self, nq_rty):
        assert nq_rty["micro_sym_B"] == "M2K"

    def test_decomposition(self, nq_rty):
        """RTY mult=50, M2K mult=5, ratio=10.

        target = 400000 * 1.07 = 428_000
        Q_total_micros = 428000 / (2200 * 5) = 38.909 → 39
        Q_B_std = 39 // 10 = 3
        Q_B_micro = 39 % 10 = 9
        """
        assert nq_rty["Q_B_std"] == 3
        assert nq_rty["Q_B_micro"] == 9


# ===================================================================
# TestSizingNoMicro — CL/HO (HO n'a pas de micro)
# ===================================================================

class TestSizingNoMicro:

    @pytest.fixture
    def cl_ho(self):
        bar = {
            "raw_price_a": 70.0,   # CL
            "raw_price_b": 2.20,   # HO ($/gallon)
            "beta_kalman": 0.72,
        }
        s4 = {"direction": "A_B", "symbol_a": "CL", "symbol_b": "HO"}
        return compute_sizing(bar, s4)

    def test_is_valid(self, cl_ho):
        assert cl_ho["is_valid"]

    def test_no_micro(self, cl_ho):
        assert cl_ho["micro_sym_B"] is None
        assert cl_ho["Q_B_micro"] == 0

    def test_std_only(self, cl_ho):
        """Arrondi en standard uniquement."""
        assert cl_ho["Q_B_std"] >= 1

    def test_residual_nonzero(self, cl_ho):
        """Sans micro, le résidu est généralement non nul."""
        # On vérifie juste que c'est calculé
        assert cl_ho["residual"] is not None


# ===================================================================
# TestBetaKalmanGuard
# ===================================================================

class TestBetaKalmanGuard:

    def _make_sizing(self, beta):
        bar = {
            "raw_price_a": 2000.0, "raw_price_b": 25.0,
            "beta_kalman": beta,
        }
        s4 = {"direction": "A_B", "symbol_a": "GC", "symbol_b": "SI"}
        return compute_sizing(bar, s4)

    def test_negative_beta_invalid(self):
        r = self._make_sizing(-0.5)
        assert not r["is_valid"]
        assert r["motif"] == "beta_kalman_non_positive"

    def test_zero_beta_invalid(self):
        r = self._make_sizing(0.0)
        assert not r["is_valid"]

    def test_positive_beta_valid(self):
        r = self._make_sizing(1.0)
        assert r["is_valid"]

    def test_invalid_sizing_all_zero(self):
        r = self._make_sizing(-1.0)
        assert r["Q_A_std"] == 0
        assert r["Q_B_std"] == 0
        assert r["notional_A"] == 0.0
