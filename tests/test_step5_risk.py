"""
Tests step5_risk — Phase 4 filtres A/B/C.

Tests synthétiques déterministes.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.step5_risk import check_filter_a, check_filter_b, check_filter_c, evaluate_filters
from config.contracts import Q_KALMAN


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def fresh_session_state():
    """État session frais (function scope pour mutation)."""
    return {
        "rolling_nis": [],
        "beta_kalman_prev": 1.0,
        "is_session_killed": False,
        "classe": "Metals",
    }


@pytest.fixture
def step4_metals():
    return {"beta_ols": 1.0}


# ===================================================================
# TestFilterA — NIS
# ===================================================================

class TestFilterA:

    def test_normal_nis_passes(self, fresh_session_state):
        """NIS=1.0 → passe."""
        assert check_filter_a(1.0, fresh_session_state)

    def test_spike_nis_blocks(self, fresh_session_state):
        """NIS=10.0 > 9.0 → bloque."""
        assert not check_filter_a(10.0, fresh_session_state)

    def test_rolling_mean_blocks(self, fresh_session_state):
        """Rolling mean > 3.0 → bloque même si NIS courant < 9."""
        # Remplir avec des valeurs élevées
        for _ in range(20):
            check_filter_a(4.0, fresh_session_state)
        # NIS courant = 1.0, mais rolling mean ~ 3.85
        assert not check_filter_a(1.0, fresh_session_state)

    def test_rolling_window_20(self, fresh_session_state):
        """Fenêtre glissante limitée à 20."""
        for _ in range(25):
            check_filter_a(1.0, fresh_session_state)
        assert len(fresh_session_state["rolling_nis"]) == 20

    def test_single_spike_recovers(self, fresh_session_state):
        """Un spike isolé ne bloque pas la barre suivante si rolling ok."""
        for _ in range(19):
            check_filter_a(1.0, fresh_session_state)
        check_filter_a(8.5, fresh_session_state)  # spike < 9 OK
        # Rolling mean = (19*1 + 8.5) / 20 = 1.375 < 3.0
        assert check_filter_a(1.0, fresh_session_state)


# ===================================================================
# TestFilterB — Vitesse Beta
# ===================================================================

class TestFilterB:

    def test_small_delta_passes(self):
        """Δβ/β = 0.001 < 0.005 → passe."""
        assert check_filter_b(1.001, 1.0)

    def test_large_delta_blocks(self):
        """Δβ/β = 0.01 > 0.005 → bloque."""
        assert not check_filter_b(1.01, 1.0)

    def test_boundary_blocks(self):
        """Δβ/β = 0.006 > 0.005 → bloque."""
        assert not check_filter_b(1.006, 1.0)

    def test_guard_near_zero_beta(self):
        """|β_prev| < 1e-6 → bloque (guard)."""
        assert not check_filter_b(0.001, 1e-7)

    def test_first_bar_with_beta_ols(self):
        """Première barre : prev = β_OLS, kalman ~ β_OLS → passe."""
        assert check_filter_b(1.0001, 1.0)

    def test_negative_beta_prev(self):
        """β_prev négatif mais abs > 1e-6 → calcul normal."""
        # Δ = |(-1.001) - (-1.0)| / |-1.0| = 0.001 < 0.005
        assert check_filter_b(-1.001, -1.0)


# ===================================================================
# TestFilterC — Dérive Macro
# ===================================================================

class TestFilterC:

    def test_metals_threshold(self):
        """Q_β=1e-7 → seuil = 4 * √(264 * 1e-7) ≈ 0.02056."""
        _, seuil = check_filter_c(1.0, 1.0, "Metals")
        expected = 4.0 * np.sqrt(264 * 1e-7)
        assert abs(seuil - expected) < 1e-10
        assert abs(seuil - 0.02056) < 0.001

    def test_energy_threshold(self):
        """Q_β=5e-7 → seuil ≈ 0.04597."""
        _, seuil = check_filter_c(1.0, 1.0, "Energy")
        expected = 4.0 * np.sqrt(264 * 5e-7)
        assert abs(seuil - expected) < 1e-10

    def test_equity_threshold(self):
        """Q_β=2e-7 → seuil ≈ 0.02906."""
        _, seuil = check_filter_c(1.0, 1.0, "Equity Index")
        expected = 4.0 * np.sqrt(264 * 2e-7)
        assert abs(seuil - expected) < 1e-10

    def test_within_threshold_passes(self):
        """Drift = 0.01 < 0.02056 → passe."""
        ok, _ = check_filter_c(1.01, 1.0, "Metals")
        assert ok

    def test_beyond_threshold_fails(self):
        """Drift = 0.03 > 0.02056 → bloque."""
        ok, _ = check_filter_c(1.03, 1.0, "Metals")
        assert not ok

    def test_energy_wider_threshold(self):
        """Energy seuil plus large → drift 0.04 passe."""
        ok, _ = check_filter_c(1.04, 1.0, "Energy")
        assert ok


# ===================================================================
# TestFilterCIrreversible
# ===================================================================

class TestFilterCIrreversible:

    def test_session_killed_stays_killed(self, fresh_session_state, step4_metals):
        """Une fois killed, toujours killed."""
        bar1 = {"nis": 1.0, "beta_kalman": 1.05}  # drift > 0.02056
        v1 = evaluate_filters(bar1, fresh_session_state, step4_metals)
        assert v1["is_session_killed"]

        # Même si beta revient à la normale
        bar2 = {"nis": 1.0, "beta_kalman": 1.0}
        v2 = evaluate_filters(bar2, fresh_session_state, step4_metals)
        assert v2["is_session_killed"]
        assert v2["motif_blocage"] == "session_killed_previous"


# ===================================================================
# TestEvaluateFilters
# ===================================================================

class TestEvaluateFilters:

    def test_all_pass(self, fresh_session_state, step4_metals):
        bar = {"nis": 1.0, "beta_kalman": 1.0001}
        v = evaluate_filters(bar, fresh_session_state, step4_metals)
        assert v["filtre_a_ok"]
        assert v["filtre_b_ok"]
        assert v["filtre_c_ok"]
        assert not v["is_session_killed"]
        assert v["motif_blocage"] is None

    def test_motif_a_priority(self, fresh_session_state, step4_metals):
        """Filtre A échoue → motif = filtre_a."""
        bar = {"nis": 10.0, "beta_kalman": 1.01}  # A bloque, B bloque aussi
        v = evaluate_filters(bar, fresh_session_state, step4_metals)
        assert not v["filtre_a_ok"]
        assert v["motif_blocage"] == "filtre_a"

    def test_motif_b_when_a_passes(self, fresh_session_state, step4_metals):
        """A passe, B échoue → motif = filtre_b."""
        bar = {"nis": 1.0, "beta_kalman": 1.01}  # B: 0.01/1.0 = 0.01 > 0.005
        v = evaluate_filters(bar, fresh_session_state, step4_metals)
        assert v["filtre_a_ok"]
        assert not v["filtre_b_ok"]
        assert v["motif_blocage"] == "filtre_b"
