"""
Step 5 — Phase 5 : Sizing beta-neutral avec découpage Standard + Micro.

PROHIBITION #3 : utiliser multiplier pour le notionnel, PAS tick_value.

Source de vérité : docs/recherche/modele_cointegration_v1_FINAL.docx — Section 8.
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.contracts import CONTRACTS, MICRO_MAP, find_micro

# Rétro-compatibilité : re-export sous l'ancien nom privé
_find_micro = find_micro


def compute_sizing(bar_state: dict, step4_result: dict) -> dict:
    """Calcul du sizing beta-neutral avec découpage Standard + Micro.

    Input:
        bar_state:     BarState_t avec raw_price_a/b et beta_kalman
        step4_result:  paramètres calibrés (direction, symbol_a/b)

    Output:
        dict avec Q_A/Q_B std/micro, notionnels, résidu, is_valid
    """
    symbol_a = step4_result["symbol_a"]
    symbol_b = step4_result["symbol_b"]
    direction = step4_result["direction"]

    # Déterminer dep/indep selon direction OLS
    if direction == "A_B":
        dep_sym, indep_sym = symbol_a, symbol_b
        raw_price_dep = bar_state["raw_price_a"]
        raw_price_indep = bar_state["raw_price_b"]
    else:
        dep_sym, indep_sym = symbol_b, symbol_a
        raw_price_dep = bar_state["raw_price_b"]
        raw_price_indep = bar_state["raw_price_a"]

    beta_kalman = bar_state["beta_kalman"]

    # Guard : beta_kalman doit être positif pour sizing
    if beta_kalman <= 0:
        return {
            "is_valid": False,
            "motif": "beta_kalman_non_positive",
            "Q_A_std": 0, "Q_A_micro": 0,
            "Q_B_std": 0, "Q_B_micro": 0,
            "micro_sym_B": None,
            "notional_A": 0.0, "target_notional_B": 0.0,
            "actual_notional_B": 0.0, "residual": 0.0,
            "beta_kalman_entry": beta_kalman,
        }

    # Étape 1 — Notionnel Leg A (dep) : 1 contrat standard
    q_a_std = 1
    q_a_micro = 0
    multiplier_a = CONTRACTS[dep_sym]["multiplier"]
    notional_a = raw_price_dep * q_a_std * multiplier_a

    # Étape 2 — Notionnel cible Leg B (indep)
    target_notional_b = notional_a * abs(beta_kalman)

    # Étape 3 — Découpage Standard + Micro
    multiplier_b_std = CONTRACTS[indep_sym]["multiplier"]
    micro_sym = find_micro(indep_sym)

    if micro_sym is not None:
        multiplier_b_micro = CONTRACTS[micro_sym]["multiplier"]
        ratio_b = multiplier_b_std / multiplier_b_micro
        q_b_total_micros_th = target_notional_b / (raw_price_indep * multiplier_b_micro)
        q_b_total_micros = max(round(q_b_total_micros_th), 1)
        q_b_std = int(q_b_total_micros // ratio_b)
        q_b_micro = int(q_b_total_micros % ratio_b)
        actual_notional_b = (
            q_b_std * multiplier_b_std + q_b_micro * multiplier_b_micro
        ) * raw_price_indep
    else:
        q_b_std = max(
            round(target_notional_b / (raw_price_indep * multiplier_b_std)), 1
        )
        q_b_micro = 0
        actual_notional_b = q_b_std * multiplier_b_std * raw_price_indep

    residual = target_notional_b - actual_notional_b

    return {
        "is_valid": True,
        "Q_A_std": q_a_std,
        "Q_A_micro": q_a_micro,
        "Q_B_std": q_b_std,
        "Q_B_micro": q_b_micro,
        "micro_sym_B": micro_sym,
        "notional_A": notional_a,
        "target_notional_B": target_notional_b,
        "actual_notional_B": actual_notional_b,
        "residual": residual,
        "beta_kalman_entry": beta_kalman,
    }


if __name__ == "__main__":
    # Quick smoke test
    bar = {
        "raw_price_a": 2000.0,
        "raw_price_b": 25.0,
        "beta_kalman": 1.0,
    }
    s4 = {"direction": "A_B", "symbol_a": "GC", "symbol_b": "SI"}
    result = compute_sizing(bar, s4)
    print("=== Sizing GC/SI ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
