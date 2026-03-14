"""
Tests V2.1 — σ_rolling : normalisation adaptative intraday.

Tests unitaires, intégration, et non-régression V1.
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
    compute_sigma_rolling,
    init_session,
    compute_signal,
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


@pytest.fixture(scope="module")
def synthetic_session(step4_synthetic):
    """Session synthétique ~264 barres avec spread OU."""
    rng = np.random.RandomState(42)
    n = 264
    alpha = step4_synthetic["alpha_ols"]
    beta = step4_synthetic["beta_ols"]
    sigma_eta = 0.002
    phi = 0.98

    log_b = np.log(25.0) + np.cumsum(rng.randn(n) * 0.001)

    spread = np.zeros(n)
    for t in range(1, n):
        spread[t] = phi * spread[t - 1] + sigma_eta * rng.randn()

    log_a = alpha + beta * log_b + spread
    price_a = np.exp(log_a)
    price_b = np.exp(log_b)

    idx = pd.date_range("2025-12-01 17:30", periods=n, freq="5min")

    return pd.DataFrame({
        "price_a": price_a,
        "price_b": price_b,
    }, index=idx)


# ===================================================================
# TestComputeSigmaRolling — unitaires
# ===================================================================

class TestComputeSigmaRolling:

    def test_constant_spread_returns_guard(self):
        """Spread constant → std=0, retourne guard 1e-10."""
        history = [1.0] * 30
        sigma = compute_sigma_rolling(history, window=20, sigma_eq_fallback=0.01)
        assert sigma == 1e-10

    def test_increasing_spread_positive(self):
        """Spread croissant linéaire → σ > 0."""
        history = [float(i) * 0.001 for i in range(30)]
        sigma = compute_sigma_rolling(history, window=20, sigma_eq_fallback=0.01)
        assert sigma > 0

    def test_burnin_empty_returns_fallback(self):
        """Historique vide → retourne σ_eq fallback."""
        sigma = compute_sigma_rolling([], window=20, sigma_eq_fallback=0.01)
        assert sigma == 0.01

    def test_burnin_one_bar_returns_fallback(self):
        """1 seule barre → retourne σ_eq fallback."""
        sigma = compute_sigma_rolling([1.0], window=20, sigma_eq_fallback=0.01)
        assert sigma == 0.01

    def test_burnin_partial_computes(self):
        """Historique >= min_bars mais < window → calcule sur ce qu'on a."""
        history = [float(i) * 0.001 for i in range(15)]
        sigma = compute_sigma_rolling(history, window=20, sigma_eq_fallback=0.01)
        # 15 >= max(10, 20//4=5) = 10, donc calcule
        assert sigma != 0.01
        assert sigma > 0

    def test_burnin_too_few_returns_fallback(self):
        """Historique < min_bars et < window → retourne fallback."""
        history = [1.0, 2.0, 3.0]
        sigma = compute_sigma_rolling(history, window=20, sigma_eq_fallback=0.01)
        # 3 < max(10, 5) = 10
        assert sigma == 0.01

    def test_window_respected(self):
        """Seules les N dernières barres sont utilisées."""
        # 100 barres : les 80 premières à 0.0, les 20 dernières ont de la variance
        rng = np.random.RandomState(42)
        history = [0.0] * 80 + list(rng.randn(20) * 0.005)
        sigma_w20 = compute_sigma_rolling(history, window=20, sigma_eq_fallback=0.01)
        sigma_w100 = compute_sigma_rolling(history, window=100, sigma_eq_fallback=0.01)
        # σ_w20 ne voit que les 20 dernières (volatiles)
        # σ_w100 voit les 80 constantes + 20 volatiles → plus petit
        assert sigma_w20 > sigma_w100

    def test_sigma_rolling_less_than_sigma_eq_typical(self):
        """σ_rolling < σ_eq sur un processus OU typique (fenêtre courte)."""
        rng = np.random.RandomState(42)
        phi = 0.98
        sigma_eta = 0.002
        spread = [0.0]
        for _ in range(200):
            spread.append(phi * spread[-1] + sigma_eta * rng.randn())
        # σ_eq théorique ≈ sigma_eta / sqrt(1 - phi²) ≈ 0.01
        sigma_eq = sigma_eta / np.sqrt(1 - phi ** 2)
        sigma_r = compute_sigma_rolling(spread, window=20, sigma_eq_fallback=sigma_eq)
        assert sigma_r < sigma_eq

    def test_guard_always_positive(self):
        """Le guard empêche σ_rolling = 0 exactement."""
        sigma = compute_sigma_rolling([5.0] * 50, window=20, sigma_eq_fallback=0.01)
        assert sigma > 0


# ===================================================================
# TestComputeSignalV2 — intégration compute_signal
# ===================================================================

class TestComputeSignalV2:

    def _make_row(self, z_target, step4, sigma_denom):
        """Construit une row qui donne le Z-score voulu avec σ donné."""
        alpha = step4["alpha_ols"]
        beta = step4["beta_ols"]
        theta = step4["theta_ou"]
        price_b = 25.0
        log_b = np.log(price_b)
        spread = z_target * sigma_denom + theta
        log_a = alpha + beta * log_b + spread
        return {"price_a": np.exp(log_a), "price_b": price_b}

    def test_returns_4_elements(self, step4_synthetic, pair_config_gc_si):
        """compute_signal retourne un tuple de 4 éléments."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        row = self._make_row(0.0, step4_synthetic, step4_synthetic["sigma_eq"])
        result = compute_signal(row, ss, step4_synthetic, 300)
        assert len(result) == 4

    def test_sigma_rolling_in_output(self, step4_synthetic, pair_config_gc_si):
        """Le 4ème élément est sigma_rolling, toujours > 0."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        row = self._make_row(0.0, step4_synthetic, step4_synthetic["sigma_eq"])
        _, _, _, sigma_r = compute_signal(row, ss, step4_synthetic, 300)
        assert sigma_r > 0

    def test_spread_history_accumulates(self, step4_synthetic, pair_config_gc_si):
        """spread_history grandit à chaque appel."""
        ss = init_session(step4_synthetic, pair_config_gc_si)
        for i in range(10):
            row = self._make_row(0.0, step4_synthetic, step4_synthetic["sigma_eq"])
            compute_signal(row, ss, step4_synthetic, 300)
        assert len(ss["spread_history"]) == 10

    def test_burnin_uses_sigma_eq(self, step4_synthetic, pair_config_gc_si):
        """Pendant le burn-in (< min_bars), σ_rolling = σ_eq."""
        ss = init_session(step4_synthetic, pair_config_gc_si, sigma_rolling_window=20)
        row = self._make_row(0.0, step4_synthetic, step4_synthetic["sigma_eq"])
        _, _, _, sigma_r = compute_signal(row, ss, step4_synthetic, 300)
        # 1 barre < 10 (min_bars) → fallback
        assert sigma_r == step4_synthetic["sigma_eq"]


# ===================================================================
# TestRunSessionV2 — intégration run_session
# ===================================================================

class TestRunSessionV2:

    def test_bar_state_has_sigma_rolling(self, synthetic_session,
                                         step4_synthetic, pair_config_gc_si):
        """BarState_t contient le champ sigma_rolling."""
        result = run_session(synthetic_session, step4_synthetic,
                             pair_config_gc_si, sigma_rolling_window=20)
        for bs in result["bar_states"]:
            assert "sigma_rolling" in bs
            assert bs["sigma_rolling"] > 0

    def test_sigma_rolling_always_positive(self, synthetic_session,
                                           step4_synthetic, pair_config_gc_si):
        """σ_rolling est toujours > 0 sur toute la session."""
        result = run_session(synthetic_session, step4_synthetic,
                             pair_config_gc_si, sigma_rolling_window=20)
        sigmas = [bs["sigma_rolling"] for bs in result["bar_states"]]
        assert all(s > 0 for s in sigmas)

    def test_p_remains_psd(self, synthetic_session, step4_synthetic,
                           pair_config_gc_si):
        """Kalman non affecté par σ_rolling — P reste PSD."""
        result = run_session(synthetic_session, step4_synthetic,
                             pair_config_gc_si, sigma_rolling_window=20)
        assert result["diagnostics"]["p_is_psd"]

    def test_different_windows_different_sigmas(self, synthetic_session,
                                                step4_synthetic,
                                                pair_config_gc_si):
        """Fenêtres différentes → σ_rolling différents (mid-session)."""
        r20 = run_session(synthetic_session, step4_synthetic,
                          pair_config_gc_si, sigma_rolling_window=20)
        r60 = run_session(synthetic_session, step4_synthetic,
                          pair_config_gc_si, sigma_rolling_window=60)
        # À la barre 100 (bien après burn-in des deux fenêtres)
        s20 = r20["bar_states"][100]["sigma_rolling"]
        s60 = r60["bar_states"][100]["sigma_rolling"]
        assert s20 != s60

    def test_window_param_propagated(self, synthetic_session,
                                     step4_synthetic, pair_config_gc_si):
        """Le paramètre sigma_rolling_window est correctement propagé."""
        r40 = run_session(synthetic_session, step4_synthetic,
                          pair_config_gc_si, sigma_rolling_window=40)
        assert "bar_states" in r40
        assert len(r40["bar_states"]) == len(synthetic_session)


# ===================================================================
# TestNonRegressionV1 — convergence avec grande fenêtre
# ===================================================================

class TestNonRegressionV1:

    def test_large_window_converges_to_sigma_eq(self, step4_synthetic):
        """Avec window très grand, σ_rolling converge vers std(spread) ≈ σ_eq."""
        rng = np.random.RandomState(42)
        phi = 0.98
        sigma_eta = 0.002
        spread = [0.0]
        for _ in range(5000):
            spread.append(phi * spread[-1] + sigma_eta * rng.randn())

        sigma_eq = sigma_eta / np.sqrt(1 - phi ** 2)
        sigma_r = compute_sigma_rolling(spread, window=5000,
                                        sigma_eq_fallback=sigma_eq)
        # Sur 5000 barres OU, std(spread) devrait être proche de σ_eq
        assert abs(sigma_r - sigma_eq) / sigma_eq < 0.1  # <10% d'écart

    def test_invariant_kalman_reset(self, synthetic_session,
                                    step4_synthetic, pair_config_gc_si):
        """Invariant 2 : Kalman réinitialisé — run_session indépendantes."""
        r1 = run_session(synthetic_session, step4_synthetic,
                         pair_config_gc_si, sigma_rolling_window=20)
        r2 = run_session(synthetic_session, step4_synthetic,
                         pair_config_gc_si, sigma_rolling_window=20)
        # Mêmes données, mêmes params → mêmes résultats
        for i in range(len(r1["bar_states"])):
            assert r1["bar_states"][i]["z_score"] == r2["bar_states"][i]["z_score"]
            assert r1["bar_states"][i]["sigma_rolling"] == r2["bar_states"][i]["sigma_rolling"]

    def test_invariant_barstate_immutable_fields(self, synthetic_session,
                                                  step4_synthetic,
                                                  pair_config_gc_si):
        """Invariant 4 : BarState_t contient tous les champs requis."""
        result = run_session(synthetic_session, step4_synthetic,
                             pair_config_gc_si, sigma_rolling_window=20)
        required_fields = ["timestamp", "raw_price_a", "raw_price_b",
                          "spread", "z_score", "sigma_rolling", "signal",
                          "beta_kalman", "alpha_kalman", "nis"]
        for bs in result["bar_states"]:
            for field in required_fields:
                assert field in bs, f"Champ manquant dans BarState_t: {field}"
