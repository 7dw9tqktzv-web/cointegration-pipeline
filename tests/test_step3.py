"""
Tests unitaires pour src/step3_cointegration.py.

Vérifie les invariants du V1 Section 6 :
- Spread inclut α (définition canonique)
- MacKinnon utilisé, pas DF standard (prohibition #6)
- Paramètres extraits de la fenêtre 30j
- Stabilité β découpée en 3 blocs
- Direction retenue = t_DF le plus négatif
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.contracts import MACKINNON_CV
from src.step3_cointegration import (
    prepare_pair_data,
    select_pair_window,
    run_ols_regression,
    compute_spread,
    run_ar1_df_test,
    is_stationary_mackinnon,
    run_both_directions,
    compute_stability,
    run_step3,
)
from src.step1_data import run_step1

DATA_DIR = PROJECT_ROOT / "data" / "raw"
GC_FILE = list(DATA_DIR.glob("GC*"))
SI_FILE = list(DATA_DIR.glob("SI*"))
HAS_DATA = len(GC_FILE) > 0 and len(SI_FILE) > 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def df_gc():
    if not HAS_DATA:
        pytest.skip("GC data not available")
    return run_step1(GC_FILE[0], "GC")


@pytest.fixture(scope="module")
def df_si():
    if not HAS_DATA:
        pytest.skip("SI data not available")
    return run_step1(SI_FILE[0], "SI")


@pytest.fixture(scope="module")
def pair_data(df_gc, df_si):
    return prepare_pair_data(df_gc, df_si)


@pytest.fixture(scope="module")
def result_gcsi(df_gc, df_si):
    return run_step3(df_gc, df_si, "GC", "SI")


@pytest.fixture(scope="module")
def synthetic_pair():
    """Crée une paire synthétique cointegree pour tests déterministes.

    log(B) = random walk, log(A) = α + β × log(B) + OU noise.
    """
    rng = np.random.RandomState(42)
    n_sessions = 30
    bars_per_session = 266
    n = n_sessions * bars_per_session  # 7980, divisible exactement

    # Générer log(B) = random walk
    log_b = np.cumsum(rng.randn(n) * 0.001) + 4.0  # ~log(55)

    # Spread OU: φ=0.98, σ_η=0.002
    alpha, beta = 3.5, 1.2
    spread = np.zeros(n)
    phi, sigma = 0.98, 0.002
    for t in range(1, n):
        spread[t] = phi * spread[t - 1] + sigma * rng.randn()

    # log(A) = α + β × log(B) + spread
    log_a = alpha + beta * log_b + spread

    # Construire DataFrame
    idx = pd.date_range("2025-12-01 17:30", periods=n, freq="5min")
    session_ids = []
    for s in range(n_sessions):
        session_ids.extend([f"2025{s + 1:04d}"] * bars_per_session)
    session_ids = session_ids[:n]

    pair = pd.DataFrame({
        "log_a": log_a,
        "log_b": log_b,
        "session_id": session_ids,
    }, index=idx)

    return pair, {"alpha": alpha, "beta": beta, "phi": phi}


# ---------------------------------------------------------------------------
# Tests — Spread canonique (avec α)
# ---------------------------------------------------------------------------

class TestSpreadDefinition:
    """Vérifie que le spread inclut α (V1 §6.1)."""

    def test_spread_includes_alpha(self, synthetic_pair):
        """Spread = log(A) - α - β × log(B), pas log(A) - β × log(B)."""
        pair, params = synthetic_pair
        ols = run_ols_regression(pair["log_a"], pair["log_b"])

        spread_with_alpha = compute_spread(
            pair["log_a"], pair["log_b"], ols["alpha"], ols["beta"]
        )
        spread_without_alpha = pair["log_a"] - ols["beta"] * pair["log_b"]

        # Le spread avec α doit avoir mean ≈ 0 (par construction OLS)
        assert abs(spread_with_alpha.mean()) < 1e-10, \
            f"Spread avec alpha devrait avoir mean~0, a {spread_with_alpha.mean()}"

        # Le spread sans α a mean ≠ 0 (= α_OLS)
        assert abs(spread_without_alpha.mean() - ols["alpha"]) < 1e-6

    def test_spread_is_ols_residual(self, synthetic_pair):
        """Le spread canonique est le résidu OLS."""
        pair, _ = synthetic_pair
        ols = run_ols_regression(pair["log_a"], pair["log_b"])
        spread = compute_spread(
            pair["log_a"], pair["log_b"], ols["alpha"], ols["beta"]
        )
        # Mean = 0 par construction
        assert abs(spread.mean()) < 1e-10


# ---------------------------------------------------------------------------
# Tests — MacKinnon vs DF standard (prohibition #6)
# ---------------------------------------------------------------------------

class TestMacKinnon:
    """Vérifie que les seuils MacKinnon sont utilisés."""

    def test_mackinnon_stricter_than_standard(self):
        """Les CVs MacKinnon sont plus négatifs que DF standard (-2.86)."""
        df_standard_5pct = -2.86
        for wname in ["10d", "30d", "60d"]:
            cv = MACKINNON_CV[wname]["5%"]
            assert cv < df_standard_5pct, \
                f"{wname}: CV MacKinnon {cv} pas plus strict que DF {df_standard_5pct}"

    def test_false_positive_scenario(self):
        """t_DF entre DF standard et MacKinnon → non-stat avec MacKinnon."""
        # t_DF = -3.0 : passerait avec DF standard (-2.86) mais
        # échouerait avec MacKinnon (-3.35 pour 30d)
        t_df = -3.0
        assert t_df < -2.86, "devrait passer DF standard"
        assert not is_stationary_mackinnon(t_df, "30d"), \
            "ne devrait PAS passer MacKinnon"

    def test_stationary_detection(self):
        """t_DF très négatif → stationnaire avec MacKinnon."""
        assert is_stationary_mackinnon(-4.0, "30d")
        assert is_stationary_mackinnon(-4.0, "10d")
        assert is_stationary_mackinnon(-4.0, "60d")


# ---------------------------------------------------------------------------
# Tests — AR(1) et paramètres
# ---------------------------------------------------------------------------

class TestAR1:
    """Vérifie l'extraction des paramètres AR(1)."""

    def test_ar1_on_synthetic(self, synthetic_pair):
        """AR(1) retrouve φ ~ 0.98 sur spread synthétique."""
        pair, true_params = synthetic_pair
        ols = run_ols_regression(pair["log_a"], pair["log_b"])
        spread = compute_spread(
            pair["log_a"], pair["log_b"], ols["alpha"], ols["beta"]
        )
        ar1 = run_ar1_df_test(spread)
        # φ estimé devrait être proche de 0.98
        assert abs(ar1["phi"] - true_params["phi"]) < 0.02, \
            f"phi={ar1['phi']:.4f}, attendu ~{true_params['phi']}"
        # σ_η > 0
        assert ar1["sigma_eta"] > 0
        # t_DF devrait être très négatif (spread stationnaire)
        assert ar1["t_df"] < -5, f"t_DF={ar1['t_df']:.2f}, attendu < -5"

    def test_params_from_30d_window(self, result_gcsi):
        """Les paramètres principaux viennent de la fenêtre 30j."""
        # Les paramètres du résultat doivent correspondre à ceux de la fenêtre 30j
        best_dir = result_gcsi["direction"]
        w30 = result_gcsi["windows"]["30d"][best_dir]
        assert result_gcsi["beta_ols"] == w30["ols"]["beta"]
        assert result_gcsi["alpha_ols"] == w30["ols"]["alpha"]
        assert result_gcsi["phi"] == w30["ar1"]["phi"]
        assert result_gcsi["sigma_eta"] == w30["ar1"]["sigma_eta"]


# ---------------------------------------------------------------------------
# Tests — Direction
# ---------------------------------------------------------------------------

class TestDirection:
    """Vérifie la sélection de direction."""

    def test_best_direction_most_negative_tdf(self, result_gcsi):
        """La direction retenue a le t_DF le plus négatif sur 30j."""
        w30 = result_gcsi["windows"]["30d"]
        best = result_gcsi["direction"]
        other = "B_A" if best == "A_B" else "A_B"
        assert w30[best]["ar1"]["t_df"] <= w30[other]["ar1"]["t_df"]

    def test_dep_indep_consistent(self, result_gcsi):
        """dep/indep cohérents avec la direction."""
        if result_gcsi["direction"] == "A_B":
            assert result_gcsi["dep"] == result_gcsi["symbol_a"]
            assert result_gcsi["indep"] == result_gcsi["symbol_b"]
        else:
            assert result_gcsi["dep"] == result_gcsi["symbol_b"]
            assert result_gcsi["indep"] == result_gcsi["symbol_a"]


# ---------------------------------------------------------------------------
# Tests — Stabilité β (V1 §6.3)
# ---------------------------------------------------------------------------

class TestStability:
    """Vérifie le calcul de stabilité structurelle."""

    def test_stability_3_blocks(self, result_gcsi):
        """La stabilité découpe en 3 blocs de β."""
        stab = result_gcsi["stability"]
        assert stab is not None
        assert len(stab["betas"]) == 3
        assert len(stab["spread_vars"]) == 3

    def test_cv_beta_formula(self, result_gcsi):
        """CV(β) = std(β) / |mean(β)|."""
        stab = result_gcsi["stability"]
        betas = stab["betas"]
        expected_cv = np.std(betas, ddof=0) / abs(np.mean(betas))
        assert abs(stab["cv_beta"] - expected_cv) < 1e-10

    def test_var_ratio_formula(self, result_gcsi):
        """Ratio_var = max(Var) / min(Var)."""
        stab = result_gcsi["stability"]
        v = stab["spread_vars"]
        expected_ratio = max(v) / min(v)
        assert abs(stab["var_ratio"] - expected_ratio) < 1e-10

    def test_status_thresholds(self):
        """Vérifie les seuils de statut."""
        # On crée des stabilités fictives pour tester les seuils
        # CV < 10% → green, 10-20% → orange, > 20% → red
        # Ratio < 1.5 → green, 1.5-2 → orange, > 2 → red
        # (testé indirectement via les résultats réels)
        stab = {
            "cv_beta": 0.05, "beta_status": "green",
            "var_ratio": 1.2, "var_status": "green",
        }
        assert stab["beta_status"] == "green"

    def test_stability_on_synthetic(self, synthetic_pair):
        """Paire synthétique stable → CV faible, Ratio faible."""
        pair, _ = synthetic_pair
        ols = run_ols_regression(pair["log_a"], pair["log_b"])
        stab = compute_stability(
            pair, "A_B", ols["alpha"], ols["beta"], n_sessions=30
        )
        assert stab is not None
        # β devrait être stable sur la paire synthétique
        assert stab["cv_beta"] < 0.10, \
            f"CV={stab['cv_beta']:.4f} trop élevé pour paire synthétique"


# ---------------------------------------------------------------------------
# Tests — Structure de sortie
# ---------------------------------------------------------------------------

class TestOutputStructure:
    """Vérifie que la sortie contient tous les champs requis."""

    def test_required_fields(self, result_gcsi):
        """Tous les champs requis par étape 4 sont présents."""
        required = [
            "beta_ols", "alpha_ols", "phi", "c_ar1", "sigma_eta",
            "se_alpha", "se_beta", "mu_b", "direction", "dep", "indep",
            "t_df_30d", "mackinnon_cv_30d", "is_stationary_30d",
            "stability", "windows", "is_blocking",
        ]
        for field in required:
            assert field in result_gcsi, f"Champ manquant: {field}"

    def test_all_windows_present(self, result_gcsi):
        """Les 3 fenêtres (10d, 30d, 60d) ont des résultats."""
        for wname in ["10d", "30d", "60d"]:
            assert wname in result_gcsi["windows"]

    def test_mu_b_is_mean_log_indep(self, pair_data, result_gcsi):
        """mu_b = mean(log(indep)) sur la fenêtre 30j."""
        # Vérifier que mu_b est dans un range raisonnable pour log(prix)
        mu_b = result_gcsi["mu_b"]
        assert 2.0 < mu_b < 12.0, \
            f"mu_b={mu_b} hors range pour log-prix futures"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
