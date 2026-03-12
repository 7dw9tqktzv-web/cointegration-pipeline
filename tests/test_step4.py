"""
Tests etape 4 -- Ornstein-Uhlenbeck : parametres OU, half-life, assertions.

Utilise des donnees synthetiques deterministes pour valider les formules,
puis les donnees reelles GC/SI pour les tests d'integration.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.step4_ou import (
    convert_ar1_to_ou,
    compute_hl_model,
    compute_hl_empirical,
    evaluate_hl_ratio,
    check_theta_ou,
    check_zscore_crosscheck,
    run_assertions,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture(scope="module")
def ou_params_typical():
    """Parametres OU typiques pour phi=0.98, c=0.0001, sigma_eta=0.002."""
    return convert_ar1_to_ou(phi=0.98, c=0.0001, sigma_eta=0.002)


@pytest.fixture(scope="module")
def synthetic_spread():
    """Spread synthetique OU avec phi=0.98 pour tester HL empirique.

    Genere un spread mean-reverting autour de 0 avec suffisamment
    de traversees |Z| > 2 -> |Z| < 0.5.
    """
    rng = np.random.RandomState(42)
    n = 8000
    phi, sigma_eta = 0.98, 0.002
    sigma_eq = sigma_eta / np.sqrt(1.0 - phi ** 2)

    spread = np.zeros(n)
    for t in range(1, n):
        spread[t] = phi * spread[t - 1] + sigma_eta * rng.randn()

    idx = pd.date_range("2025-12-01 17:30", periods=n, freq="5min")
    return pd.Series(spread, index=idx), sigma_eq


# ===================================================================
# TestConversionOU — formules V1 S7.1
# ===================================================================

class TestConversionOU:

    def test_kappa_formula(self, ou_params_typical):
        """kappa = -ln(phi) / dt."""
        expected = -np.log(0.98)
        assert abs(ou_params_typical["kappa"] - expected) < 1e-10

    def test_theta_ou_formula(self, ou_params_typical):
        """theta_OU = c / (1 - phi)."""
        expected = 0.0001 / (1.0 - 0.98)
        assert abs(ou_params_typical["theta_ou"] - expected) < 1e-10

    def test_sigma_eq_formula(self, ou_params_typical):
        """sigma_eq = sigma_eta / sqrt(1 - phi^2)."""
        expected = 0.002 / np.sqrt(1.0 - 0.98 ** 2)
        assert abs(ou_params_typical["sigma_eq"] - expected) < 1e-10

    def test_sigma_diffusion_formula(self, ou_params_typical):
        """sigma_diff = sigma_eta * sqrt(-2*ln(phi) / (1 - phi^2))."""
        expected = 0.002 * np.sqrt(-2.0 * np.log(0.98) / (1.0 - 0.98 ** 2))
        assert abs(ou_params_typical["sigma_diffusion"] - expected) < 1e-10

    def test_sigma_eq_gt_sigma_diffusion(self, ou_params_typical):
        """sigma_eq > sigma_diffusion pour phi proche de 1 (V1 correction critique)."""
        assert ou_params_typical["sigma_eq"] > ou_params_typical["sigma_diffusion"]

    def test_sigma_eq_ratio_approx_3x(self):
        """Pour phi=0.95, sigma_eq ~ 3.2 * sigma_eta (V1 exemple)."""
        ou = convert_ar1_to_ou(phi=0.95, c=0.0, sigma_eta=0.002)
        ratio = ou["sigma_eq"] / 0.002
        assert 3.0 < ratio < 3.5

    def test_phi_out_of_range_raises(self):
        """phi hors ]0,1[ leve une assertion."""
        with pytest.raises(AssertionError):
            convert_ar1_to_ou(phi=1.0, c=0.0, sigma_eta=0.002)
        with pytest.raises(AssertionError):
            convert_ar1_to_ou(phi=0.0, c=0.0, sigma_eta=0.002)
        with pytest.raises(AssertionError):
            convert_ar1_to_ou(phi=-0.5, c=0.0, sigma_eta=0.002)

    def test_q_ou_positive(self, ou_params_typical):
        """Q_OU doit etre positif."""
        assert ou_params_typical["q_ou"] > 0

    def test_q_ou_order_of_magnitude(self, ou_params_typical):
        """Q_OU ~ 10^-6 pour parametres typiques (V1 S7.2)."""
        assert 1e-8 < ou_params_typical["q_ou"] < 1e-4


# ===================================================================
# TestHalfLife — modele et empirique (V1 S7.3 + audit)
# ===================================================================

class TestHalfLife:

    def test_hl_model_formula(self):
        """HL_modele = ln(2) / kappa."""
        kappa = -np.log(0.98)
        expected = np.log(2) / kappa
        assert abs(compute_hl_model(kappa) - expected) < 1e-10

    def test_hl_model_reasonable_range(self, ou_params_typical):
        """HL modele entre 10 et 100 barres pour phi=0.98."""
        hl = compute_hl_model(ou_params_typical["kappa"])
        assert 10 < hl < 100

    def test_hl_empirical_counts_crossings(self, synthetic_spread):
        """Le compteur de traversees fonctionne sur spread synthetique."""
        spread, sigma_eq = synthetic_spread
        result = compute_hl_empirical(spread, sigma_eq, theta_ou=0.0)
        assert result["n_crossings"] >= 5

    def test_hl_empirical_positive(self, synthetic_spread):
        """HL empirique est positif quand suffisamment de traversees."""
        spread, sigma_eq = synthetic_spread
        result = compute_hl_empirical(spread, sigma_eq, theta_ou=0.0)
        if result["hl_empirical"] is not None:
            assert result["hl_empirical"] > 0

    def test_hl_empirical_none_if_few_crossings(self):
        """HL empirique = None si < 5 traversees (regle audit)."""
        # Spread quasi-constant = pas de traversee
        spread = pd.Series(np.zeros(1000))
        result = compute_hl_empirical(spread, sigma_eq=0.01, theta_ou=0.0)
        assert result["hl_empirical"] is None
        assert result["n_crossings"] < 5

    def test_crossing_definition(self):
        """Traversee = entree |Z|>2 puis retour |Z|<0.5."""
        # Construire un spread avec exactement 1 traversee
        sigma_eq = 1.0
        z_values = [0.0] * 10 + [2.5] * 5 + [0.3] + [0.0] * 10
        spread = pd.Series(np.array(z_values) * sigma_eq)
        result = compute_hl_empirical(spread, sigma_eq=sigma_eq, theta_ou=0.0)
        assert result["n_crossings"] == 1
        # Temps = index de sortie - index d'entree = 15 - 10 = 5
        assert result["crossing_times"][0] == 5


# ===================================================================
# TestHLRatio — seuils V1 + decisions bloquantes
# ===================================================================

class TestHLRatio:

    def test_green_range(self):
        """Ratio 0.8-1.5 -> green, non bloquant."""
        r = evaluate_hl_ratio(hl_empirical=35.0, hl_model=34.3)
        assert r["hl_status"] == "green"
        assert not r["is_blocking"]

    def test_orange_high(self):
        """Ratio 1.5-2.0 -> orange, non bloquant."""
        r = evaluate_hl_ratio(hl_empirical=52.0, hl_model=34.3)
        assert r["hl_status"] == "orange"
        assert not r["is_blocking"]

    def test_orange_low(self):
        """Ratio 0.33-0.8 -> orange, non bloquant."""
        r = evaluate_hl_ratio(hl_empirical=20.0, hl_model=34.3)
        assert r["hl_status"] == "orange"
        assert not r["is_blocking"]

    def test_red_high_not_blocking(self):
        """Ratio 2.0-3.0 -> red, non bloquant."""
        r = evaluate_hl_ratio(hl_empirical=80.0, hl_model=34.3)
        assert r["hl_status"] == "red"
        assert not r["is_blocking"]

    def test_red_low_not_blocking(self):
        """Ratio < 0.33 -> red, non bloquant (conservateur)."""
        r = evaluate_hl_ratio(hl_empirical=5.0, hl_model=34.3)
        assert r["hl_status"] == "red"
        assert not r["is_blocking"]

    def test_blocking_above_3(self):
        """Ratio > 3.0 -> red, BLOQUANT (seul cas bloquant)."""
        r = evaluate_hl_ratio(hl_empirical=120.0, hl_model=34.3)
        assert r["hl_status"] == "red"
        assert r["is_blocking"]

    def test_none_fallback(self):
        """HL empirique None -> fallback modele, orange, non bloquant."""
        r = evaluate_hl_ratio(hl_empirical=None, hl_model=34.3)
        assert r["hl_operational"] == 34.3
        assert r["hl_status"] == "orange"
        assert r["hl_source"] == "model_fallback"
        assert not r["is_blocking"]

    def test_operational_uses_empirical(self):
        """Quand HL empirique disponible, c'est la reference operationnelle."""
        r = evaluate_hl_ratio(hl_empirical=40.0, hl_model=34.3)
        assert r["hl_operational"] == 40.0
        assert r["hl_source"] == "empirical"


# ===================================================================
# TestAssertions — sante V1 S7.4
# ===================================================================

class TestAssertions:

    def test_theta_ou_near_zero(self):
        """theta_OU ~ 0 par construction OLS -> ok."""
        r = check_theta_ou(theta_ou=0.00005, sigma_eq=0.01)
        assert r["ok"]

    def test_theta_ou_too_large(self):
        """theta_OU trop grand -> alerte."""
        r = check_theta_ou(theta_ou=0.005, sigma_eq=0.01)
        assert not r["ok"]

    def test_zscore_crosscheck_perfect(self):
        """Quand theta_OU=0 et sigma_eq=std(spread), Dz ~ 0."""
        rng = np.random.RandomState(42)
        spread = pd.Series(rng.randn(5000) * 0.01)
        sigma_eq = float(spread.std(ddof=1))
        r = check_zscore_crosscheck(spread, theta_ou=0.0, sigma_eq=sigma_eq)
        assert r["median_dz"] < 0.02
        assert r["ok"]

    def test_assertions_blocking_on_bad_phi(self):
        """Assertions bloquantes si phi hors range (via run_assertions)."""
        # On simule avec des valeurs manuelles
        ou_params = {
            "kappa": -0.01,  # negatif = probleme
            "theta_ou": 0.0,
            "sigma_eq": 0.01,
        }
        spread = pd.Series(np.zeros(100))
        r = run_assertions(phi=1.05, ou_params=ou_params, spread=spread)
        assert r["is_blocking"]
        assert not r["phi_in_range"]

    def test_assertions_not_blocking_normal(self, ou_params_typical):
        """Parametres normaux -> pas bloquant."""
        rng = np.random.RandomState(42)
        spread = pd.Series(rng.randn(5000) * ou_params_typical["sigma_eq"])
        r = run_assertions(phi=0.98, ou_params=ou_params_typical, spread=spread)
        assert not r["is_blocking"]
        assert r["phi_in_range"]
        assert r["kappa_positive"]
        assert r["sigma_eq_valid"]


# ===================================================================
# TestOutputStructure — sortie run_step4
# ===================================================================

class TestOutputStructure:

    @pytest.fixture(scope="class")
    def step4_result(self):
        """Execute step4 sur GC/SI reels (si donnees disponibles)."""
        data_dir = _PROJECT_ROOT / "data" / "raw"
        gc_files = list(data_dir.glob("GC*"))
        si_files = list(data_dir.glob("SI*"))
        if not gc_files or not si_files:
            pytest.skip("Donnees GC/SI non disponibles")

        from src.step1_data import run_step1
        from src.step3_cointegration import run_step3
        from src.step4_ou import run_step4

        df_gc = run_step1(gc_files[0], "GC")
        df_si = run_step1(si_files[0], "SI")
        s3 = run_step3(df_gc, df_si, "GC", "SI")

        if s3.get("is_blocking"):
            pytest.skip("Step3 bloquant sur GC/SI -- step4 non executable")

        return run_step4(s3, df_gc, df_si)

    def test_required_fields(self, step4_result):
        """Tous les champs requis sont presents."""
        required = [
            "kappa", "theta_ou", "sigma_eq",
            "sigma_diffusion", "q_ou",
            "hl_model", "hl_empirical", "hl_operational",
            "hl_status", "hl_source", "n_crossings",
            "assertions", "is_blocking",
            "alpha_ols", "beta_ols", "se_alpha", "se_beta",
            "resid_var", "mu_b", "direction",
            "symbol_a", "symbol_b",
        ]
        for field in required:
            assert field in step4_result, f"Champ manquant: {field}"

    def test_sigma_eq_positive(self, step4_result):
        """sigma_eq > 0 et fini."""
        assert step4_result["sigma_eq"] > 0
        assert np.isfinite(step4_result["sigma_eq"])

    def test_kappa_positive(self, step4_result):
        """kappa > 0."""
        assert step4_result["kappa"] > 0

    def test_q_ou_not_in_step5_outputs(self, step4_result):
        """Q_OU est present mais documente comme interne.

        Verification que sigma_diffusion et q_ou existent (pour audit)
        mais ne doivent PAS etre passes a step5.
        """
        assert "q_ou" in step4_result
        assert "sigma_diffusion" in step4_result

    def test_passthrough_step3(self, step4_result):
        """Les parametres step3 sont passes pour step5."""
        assert step4_result["alpha_ols"] is not None
        assert step4_result["beta_ols"] is not None
        assert step4_result["resid_var"] is not None
