"""
Tests step5_engine — Kalman, signal machine, session loop.

Tests synthétiques déterministes.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.step5_engine import (
    _compute_t_limite,
    compute_sigma_rolling,
    init_session,
    compute_signal,
    kalman_update,
    _execute_signal,
    _open_position,
    run_session,
)
from config.contracts import PAIRS


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture(scope="module")
def step4_synthetic():
    """Paramètres step4 synthétiques (GC/SI-like)."""
    return {
        "alpha_ols": 0.5,
        "beta_ols": 1.0,
        "theta_ou": 0.0,
        "sigma_eq": 0.01,
        "kappa": 0.02,
        "hl_operational": 34.0,
        "se_alpha": 0.001,
        "se_beta": 0.001,
        "resid_var": 1e-4,
        "mu_b": 1.0,
        "direction": "A_B",
        "symbol_a": "GC",
        "symbol_b": "SI",
        "phi": 0.98,
        "c_ar1": 0.0001,
        "sigma_eta": 0.002,
    }


@pytest.fixture(scope="module")
def pair_config_gc_si():
    return PAIRS["GC_SI"]


@pytest.fixture
def session_state(step4_synthetic, pair_config_gc_si):
    """État session frais (function scope)."""
    return init_session(step4_synthetic, pair_config_gc_si)


@pytest.fixture(scope="module")
def synthetic_session(step4_synthetic):
    """Session synthétique ~264 barres avec spread OU."""
    rng = np.random.RandomState(42)
    n = 264
    alpha = step4_synthetic["alpha_ols"]
    beta = step4_synthetic["beta_ols"]
    sigma_eta = 0.002
    phi = 0.98

    # Prix B : random walk en log
    log_b = np.log(25.0) + np.cumsum(rng.randn(n) * 0.001)

    # Spread OU
    spread = np.zeros(n)
    for t in range(1, n):
        spread[t] = phi * spread[t - 1] + sigma_eta * rng.randn()

    # Prix A = exp(alpha + beta * log_b + spread)
    log_a = alpha + beta * log_b + spread
    price_a = np.exp(log_a)
    price_b = np.exp(log_b)

    # Index : session CME 17:30 → 15:25 (264 barres de 5min)
    idx = pd.date_range("2025-12-01 17:30", periods=n, freq="5min")

    return pd.DataFrame({
        "price_a": price_a,
        "price_b": price_b,
    }, index=idx)


# ===================================================================
# TestTimeLock
# ===================================================================

class TestTimeLock:

    def test_t_limite_no_pit(self):
        """T_limite = 930 - 34*5 = 760 min."""
        t = _compute_t_limite(34.0, {"t_close_pit": None})
        assert t == 760

    def test_t_limite_with_pit_constraining(self):
        """pit=13:20=800 > 760 → T_limite = 760."""
        t = _compute_t_limite(34.0, {"t_close_pit": "13:20"})
        assert t == 760

    def test_t_limite_pit_more_constraining(self):
        """hl=10 → from_hl=880, pit=800 → T_limite = 800."""
        t = _compute_t_limite(10.0, {"t_close_pit": "13:20"})
        assert t == 800

    def test_t_limite_large_hl(self):
        """hl=200 → from_hl=-70, pit=930 → T_limite = -70."""
        t = _compute_t_limite(200.0, {"t_close_pit": None})
        assert t == -70  # Pas de trading possible


# ===================================================================
# TestInitSession
# ===================================================================

class TestInitSession:

    def test_state_created(self, session_state):
        assert session_state["position"] is None
        assert not session_state["is_armed_long"]
        assert not session_state["is_armed_short"]

    def test_kalman_init(self, session_state):
        """x = [alpha, beta], P diagonal."""
        assert session_state["x"][0] == 0.5
        assert session_state["x"][1] == 1.0
        assert session_state["P"].shape == (2, 2)

    def test_beta_prev_is_beta_ols(self, session_state):
        assert session_state["beta_kalman_prev"] == 1.0

    def test_classe_stored(self, session_state):
        assert session_state["classe"] == "Metals"


# ===================================================================
# TestKalmanUpdate
# ===================================================================

class TestKalmanUpdate:

    def test_beta_stable_on_calibrated_data(self, step4_synthetic,
                                             pair_config_gc_si):
        """β_Kalman reste proche de β_OLS sur données calibrées."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        rng = np.random.RandomState(42)

        for _ in range(200):
            log_b = np.log(25.0) + rng.randn() * 0.001
            spread = rng.randn() * 0.002
            log_a = 0.5 + 1.0 * log_b + spread
            row = {"price_a": np.exp(log_a), "price_b": np.exp(log_b)}
            result = kalman_update(row, ss)

        assert abs(result["beta_kalman"] - 1.0) < 0.05

    def test_joseph_form_p_symmetric(self, step4_synthetic,
                                      pair_config_gc_si):
        """P reste symétrique après 500 itérations."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        rng = np.random.RandomState(42)

        for _ in range(500):
            log_b = np.log(25.0) + rng.randn() * 0.001
            log_a = 0.5 + 1.0 * log_b + rng.randn() * 0.002
            row = {"price_a": np.exp(log_a), "price_b": np.exp(log_b)}
            kalman_update(row, ss)

        P = ss["P"]
        assert np.allclose(P, P.T, atol=1e-15)

    def test_joseph_form_p_psd(self, step4_synthetic, pair_config_gc_si):
        """P reste positive semi-definie après 500 itérations."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        rng = np.random.RandomState(42)

        for _ in range(500):
            log_b = np.log(25.0) + rng.randn() * 0.001
            log_a = 0.5 + 1.0 * log_b + rng.randn() * 0.002
            row = {"price_a": np.exp(log_a), "price_b": np.exp(log_b)}
            kalman_update(row, ss)

        eigvals = np.linalg.eigvalsh(ss["P"])
        assert np.all(eigvals > 0)

    def test_nis_output(self, session_state):
        """NIS est positif et fini."""
        row = {"price_a": np.exp(0.5 + 1.0 * np.log(25.0)),
               "price_b": 25.0}
        result = kalman_update(row, session_state)
        assert result["nis"] >= 0
        assert np.isfinite(result["nis"])


# ===================================================================
# TestSignalMachine
# ===================================================================

class TestSignalMachine:

    def _make_row(self, z, step4):
        """Construit une row qui donne le Z-score voulu."""
        alpha = step4["alpha_ols"]
        beta = step4["beta_ols"]
        sigma_eq = step4["sigma_eq"]
        theta = step4["theta_ou"]
        price_b = 25.0
        log_b = np.log(price_b)
        spread = z * sigma_eq + theta
        log_a = alpha + beta * log_b + spread
        return {"price_a": np.exp(log_a), "price_b": price_b}

    def test_armement_long(self, session_state, step4_synthetic):
        """Z < -2.5 → armed long."""
        row = self._make_row(-2.6, step4_synthetic)
        compute_signal(row, session_state, step4_synthetic, 300)
        assert session_state["is_armed_long"]

    def test_armement_short(self, step4_synthetic, pair_config_gc_si):
        ss = init_session(step4_synthetic, pair_config_gc_si)
        row = self._make_row(2.6, step4_synthetic)
        compute_signal(row, ss, step4_synthetic, 300)
        assert ss["is_armed_short"]

    def test_trigger_long(self, step4_synthetic, pair_config_gc_si):
        """Armed long + Z > -2.0 → ENTRY_LONG."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        ss["is_armed_long"] = True
        row = self._make_row(-1.9, step4_synthetic)
        signal, _, _, _ = compute_signal(row, ss, step4_synthetic, 300)
        assert signal == "ENTRY_LONG"
        assert not ss["is_armed_long"]

    def test_trigger_short(self, step4_synthetic, pair_config_gc_si):
        ss = init_session(step4_synthetic, pair_config_gc_si)
        ss["is_armed_short"] = True
        row = self._make_row(1.9, step4_synthetic)
        signal, _, _, _ = compute_signal(row, ss, step4_synthetic, 300)
        assert signal == "ENTRY_SHORT"

    def test_tp(self, step4_synthetic, pair_config_gc_si):
        """Position LONG + |Z| < 0.5 → TP."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        ss["position"] = "LONG"
        row = self._make_row(0.3, step4_synthetic)
        signal, _, _, _ = compute_signal(row, ss, step4_synthetic, 300)
        assert signal == "TP"

    def test_sl_long(self, step4_synthetic, pair_config_gc_si):
        """Position LONG + Z < -3.0 → SL."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        ss["position"] = "LONG"
        row = self._make_row(-3.1, step4_synthetic)
        signal, _, _, _ = compute_signal(row, ss, step4_synthetic, 300)
        assert signal == "SL"

    def test_sl_short(self, step4_synthetic, pair_config_gc_si):
        """Position SHORT + Z > 3.0 → SL."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        ss["position"] = "SHORT"
        row = self._make_row(3.1, step4_synthetic)
        signal, _, _, _ = compute_signal(row, ss, step4_synthetic, 300)
        assert signal == "SL"

    def test_sl_priority_over_tp(self, step4_synthetic, pair_config_gc_si):
        """SL prioritaire sur TP (Z < -3.0, impossible |Z|<0.5 en même temps)."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        ss["position"] = "LONG"
        row = self._make_row(-3.5, step4_synthetic)
        signal, _, _, _ = compute_signal(row, ss, step4_synthetic, 300)
        assert signal == "SL"

    def test_session_close(self, step4_synthetic, pair_config_gc_si):
        """Position ouverte à 15:25 → SESSION_CLOSE."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        ss["position"] = "LONG"
        row = self._make_row(1.0, step4_synthetic)
        signal, _, _, _ = compute_signal(row, ss, step4_synthetic, 925)
        assert signal == "SESSION_CLOSE"

    def test_session_close_priority(self, step4_synthetic, pair_config_gc_si):
        """SESSION_CLOSE prioritaire même si SL conditions."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        ss["position"] = "LONG"
        row = self._make_row(-3.5, step4_synthetic)
        signal, _, _, _ = compute_signal(row, ss, step4_synthetic, 925)
        assert signal == "SESSION_CLOSE"

    def test_disarm_on_sl_zone(self, step4_synthetic, pair_config_gc_si):
        """Armed long + Z < -3.0 sans position → désarmé."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        ss["is_armed_long"] = True
        row = self._make_row(-3.1, step4_synthetic)
        signal, _, _, _ = compute_signal(row, ss, step4_synthetic, 300)
        assert signal is None
        assert not ss["is_armed_long"]

    def test_independent_armement(self, step4_synthetic, pair_config_gc_si):
        """Armer long ne reset pas le flag short (audit #3).

        On ne peut pas armer les deux via signal processing car
        z > 2.5 déclenche aussi le trigger long (z > -2.0).
        On vérifie l'indépendance structurelle des flags.
        """
        ss = init_session(step4_synthetic, pair_config_gc_si)
        # Arm long via signal (z=-2.6 dans [-3.0, -2.5])
        row = self._make_row(-2.6, step4_synthetic)
        compute_signal(row, ss, step4_synthetic, 300)
        assert ss["is_armed_long"]
        assert not ss["is_armed_short"]
        # Les deux flags peuvent coexister au niveau état
        ss["is_armed_short"] = True
        assert ss["is_armed_long"] and ss["is_armed_short"]

    def test_returns_tuple(self, step4_synthetic, pair_config_gc_si):
        """compute_signal retourne (signal, spread, z, sigma_rolling)."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        row = self._make_row(0.0, step4_synthetic)
        result = compute_signal(row, ss, step4_synthetic, 300)
        assert len(result) == 4
        signal, spread, z, sigma_r = result
        assert isinstance(spread, float)
        assert isinstance(z, float)
        assert isinstance(sigma_r, float)
        assert sigma_r > 0

    def test_spread_z_consistency(self, step4_synthetic, pair_config_gc_si):
        """z = (spread - theta_ou) / sigma_rolling."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        row = self._make_row(1.5, step4_synthetic)
        _, spread, z, sigma_r = compute_signal(row, ss, step4_synthetic, 300)
        expected_z = (spread - step4_synthetic["theta_ou"]) / sigma_r
        assert abs(z - expected_z) < 1e-10


# ===================================================================
# TestTimeLockSignal
# ===================================================================

class TestTimeLockSignal:

    def test_no_armement_after_t_limite(self, step4_synthetic,
                                        pair_config_gc_si):
        """Pas d'armement après T_limite."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        row = self._make_row(-2.6, step4_synthetic)
        compute_signal(row, ss, step4_synthetic, 900)  # après T_limite
        assert not ss["is_armed_long"]

    def test_tp_still_works_after_t_limite(self, step4_synthetic,
                                            pair_config_gc_si):
        """TP fonctionne toujours après time-lock."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        ss["position"] = "LONG"
        row = self._make_row(0.3, step4_synthetic)
        signal, _, _, _ = compute_signal(row, ss, step4_synthetic, 900)
        assert signal == "TP"

    def _make_row(self, z, step4):
        alpha = step4["alpha_ols"]
        beta = step4["beta_ols"]
        sigma_eq = step4["sigma_eq"]
        theta = step4["theta_ou"]
        price_b = 25.0
        log_b = np.log(price_b)
        spread = z * sigma_eq + theta
        log_a = alpha + beta * log_b + spread
        return {"price_a": np.exp(log_a), "price_b": price_b}


# ===================================================================
# TestExecuteSignalFilterC — Bug fix: signal=None + Filtre C + position
# ===================================================================

class TestExecuteSignalFilterC:

    def test_sortie_forcee_without_signal(self, step4_synthetic,
                                          pair_config_gc_si):
        """Position ouverte, signal=None, Filtre C déclenché → SORTIE_FORCEE.

        Scénario : LONG ouvert, Z à −1.5 (zone neutre, pas de signal),
        mais β_Kalman a dérivé au-delà du seuil Filtre C.
        """
        ss = init_session(step4_synthetic, pair_config_gc_si)

        # Simuler une position ouverte
        bar_entry = {
            "timestamp": pd.Timestamp("2025-01-02 08:00"),
            "raw_price_a": 2000.0, "raw_price_b": 25.0,
            "spread": 0.0, "z_score": -2.5, "signal": "ENTRY_LONG",
            "beta_kalman": 1.0, "alpha_kalman": 0.5, "nis": 1.0,
        }
        sizing = {"is_valid": True, "Q_A_std": 1, "Q_B_std": 1,
                  "Q_B_micro": 0, "notional_A": 200_000.0}
        _open_position(bar_entry, "ENTRY_LONG", sizing, ss)
        assert ss["position"] == "LONG"

        # Barre suivante : signal=None (z neutre), mais Filtre C déclenché
        bar_neutral = {
            "timestamp": pd.Timestamp("2025-01-02 08:05"),
            "raw_price_a": 2000.0, "raw_price_b": 25.0,
            "spread": 0.0, "z_score": -1.5, "signal": None,
            "beta_kalman": 1.05, "alpha_kalman": 0.5, "nis": 1.0,
        }
        verdict_killed = {
            "filtre_a_ok": True, "filtre_b_ok": True,
            "filtre_c_ok": False, "is_session_killed": True,
            "motif_blocage": "filtre_c_drift=0.0500_seuil=0.0206",
        }

        _execute_signal(bar_neutral, verdict_killed, ss, step4_synthetic)

        # Position doit être fermée en SORTIE_FORCEE
        assert ss["position"] is None
        assert len(ss["trades"]) == 1
        assert ss["trades"][0]["exit_motif"] == "SORTIE_FORCEE"

    def test_sortie_forcee_does_not_override_tp(self, step4_synthetic,
                                                 pair_config_gc_si):
        """Si TP et Filtre C simultanés, TP est exécuté (pas SORTIE_FORCEE)."""
        ss = init_session(step4_synthetic, pair_config_gc_si)

        bar_entry = {
            "timestamp": pd.Timestamp("2025-01-02 08:00"),
            "raw_price_a": 2000.0, "raw_price_b": 25.0,
            "spread": 0.0, "z_score": -2.5, "signal": "ENTRY_LONG",
            "beta_kalman": 1.0, "alpha_kalman": 0.5, "nis": 1.0,
        }
        sizing = {"is_valid": True, "Q_A_std": 1, "Q_B_std": 1,
                  "Q_B_micro": 0, "notional_A": 200_000.0}
        _open_position(bar_entry, "ENTRY_LONG", sizing, ss)

        # TP signal + Filtre C killed simultanément
        bar_tp = {
            "timestamp": pd.Timestamp("2025-01-02 08:10"),
            "raw_price_a": 2000.0, "raw_price_b": 25.0,
            "spread": 0.0, "z_score": 0.3, "signal": "TP",
            "beta_kalman": 1.05, "alpha_kalman": 0.5, "nis": 1.0,
        }
        verdict_killed = {
            "filtre_a_ok": True, "filtre_b_ok": True,
            "filtre_c_ok": False, "is_session_killed": True,
            "motif_blocage": "filtre_c_drift=0.0500_seuil=0.0206",
        }

        _execute_signal(bar_tp, verdict_killed, ss, step4_synthetic)

        assert ss["position"] is None
        assert ss["trades"][0]["exit_motif"] == "TAKE_PROFIT"

    def test_no_position_killed_blocks_entry(self, step4_synthetic,
                                              pair_config_gc_si):
        """Sans position, session killed → entrée bloquée (pas de crash)."""
        ss = init_session(step4_synthetic, pair_config_gc_si)

        bar_entry = {
            "timestamp": pd.Timestamp("2025-01-02 08:00"),
            "raw_price_a": 2000.0, "raw_price_b": 25.0,
            "spread": 0.0, "z_score": -2.5, "signal": "ENTRY_LONG",
            "beta_kalman": 1.05, "alpha_kalman": 0.5, "nis": 1.0,
        }
        verdict_killed = {
            "filtre_a_ok": True, "filtre_b_ok": True,
            "filtre_c_ok": False, "is_session_killed": True,
            "motif_blocage": "filtre_c_drift=0.0500_seuil=0.0206",
        }

        _execute_signal(bar_entry, verdict_killed, ss, step4_synthetic)

        # Pas de position ouverte
        assert ss["position"] is None
        assert len(ss["trades"]) == 0


# ===================================================================
# TestRunSession
# ===================================================================

class TestRunSession:

    def test_no_crash(self, synthetic_session, step4_synthetic,
                      pair_config_gc_si):
        """La session complète tourne sans erreur."""
        result = run_session(synthetic_session, step4_synthetic,
                             pair_config_gc_si)
        assert "bar_states" in result
        assert "trades" in result
        assert "diagnostics" in result

    def test_bar_count(self, synthetic_session, step4_synthetic,
                       pair_config_gc_si):
        """Nombre de bar_states = nombre de lignes."""
        result = run_session(synthetic_session, step4_synthetic,
                             pair_config_gc_si)
        assert len(result["bar_states"]) == len(synthetic_session)

    def test_p_remains_psd(self, synthetic_session, step4_synthetic,
                           pair_config_gc_si):
        """P reste PSD sur toute la session."""
        result = run_session(synthetic_session, step4_synthetic,
                             pair_config_gc_si)
        assert result["diagnostics"]["p_is_psd"]

    def test_nis_mean_reasonable(self, synthetic_session, step4_synthetic,
                                 pair_config_gc_si):
        """NIS moyen entre 0.1 et 10 sur données calibrées."""
        result = run_session(synthetic_session, step4_synthetic,
                             pair_config_gc_si)
        nis_mean = result["diagnostics"]["nis_mean"]
        assert 0.1 < nis_mean < 10.0

    def test_diagnostics_complete(self, synthetic_session, step4_synthetic,
                                   pair_config_gc_si):
        """Tous les champs diagnostics présents."""
        result = run_session(synthetic_session, step4_synthetic,
                             pair_config_gc_si)
        diag = result["diagnostics"]
        for key in ["n_bars", "n_trades", "nis_mean", "nis_max",
                     "p_eigenvalues", "p_is_psd", "session_killed",
                     "t_limite"]:
            assert key in diag, f"Champ manquant: {key}"
