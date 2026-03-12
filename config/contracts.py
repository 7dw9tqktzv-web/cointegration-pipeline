"""
Configuration des contrats futures CME — Tables Annexes A et D du V1.

Source de vérité : docs/recherche/modele_cointegration_v1_FINAL.docx
Ne jamais modifier ces valeurs sans vérifier le document.
"""

from typing import TypedDict


# ---------------------------------------------------------------------------
# Annexe D — Multipliers (Point Value) par contrat
# CRITIQUE : multiplier ≠ tick_value. Relation : multiplier = tick_value / tick_size
# Le notionnel utilise EXCLUSIVEMENT le multiplier.
# ---------------------------------------------------------------------------

class ContractSpec(TypedDict):
    tick_size: float
    tick_value: float
    multiplier: float


CONTRACTS: dict[str, ContractSpec] = {
    # --- Indices ---
    "NQ":  {"tick_size": 0.25,   "tick_value": 5.00,   "multiplier": 20},
    "ES":  {"tick_size": 0.25,   "tick_value": 12.50,  "multiplier": 50},
    "RTY": {"tick_size": 0.10,   "tick_value": 5.00,   "multiplier": 50},
    "YM":  {"tick_size": 1.00,   "tick_value": 5.00,   "multiplier": 5},
    "MNQ": {"tick_size": 0.25,   "tick_value": 0.50,   "multiplier": 2},
    "MYM": {"tick_size": 1.00,   "tick_value": 0.50,   "multiplier": 0.5},
    "MES": {"tick_size": 0.25,   "tick_value": 1.25,   "multiplier": 5},
    "M2K": {"tick_size": 0.10,   "tick_value": 0.50,   "multiplier": 5},
    # --- Energy ---
    "CL":  {"tick_size": 0.01,   "tick_value": 10.00,  "multiplier": 1000},
    "NG":  {"tick_size": 0.001,  "tick_value": 10.00,  "multiplier": 10_000},
    "BZ":  {"tick_size": 0.01,   "tick_value": 10.00,  "multiplier": 1000},
    "HO":  {"tick_size": 0.0001, "tick_value": 4.20,   "multiplier": 42_000},
    "RB":  {"tick_size": 0.0001, "tick_value": 4.20,   "multiplier": 42_000},
    "MCL": {"tick_size": 0.01,   "tick_value": 1.00,   "multiplier": 100},
    "QG":  {"tick_size": 0.005,  "tick_value": 12.50,  "multiplier": 2500},
    # --- Metals ---
    "GC":  {"tick_size": 0.10,   "tick_value": 10.00,  "multiplier": 100},
    "SI":  {"tick_size": 0.005,  "tick_value": 25.00,  "multiplier": 5000},
    "HG":  {"tick_size": 0.0005, "tick_value": 12.50,  "multiplier": 25_000},
    "PL":  {"tick_size": 0.10,   "tick_value": 5.00,   "multiplier": 50},
    "PA":  {"tick_size": 0.50,   "tick_value": 50.00,  "multiplier": 100},
    "MGC": {"tick_size": 0.10,   "tick_value": 1.00,   "multiplier": 10},
    "SIL": {"tick_size": 0.005,  "tick_value": 5.00,   "multiplier": 1000},
    "MHG": {"tick_size": 0.0005, "tick_value": 1.25,   "multiplier": 2500},
    # --- Grains ---
    "ZC":  {"tick_size": 0.25,   "tick_value": 12.50,  "multiplier": 50},
    "ZW":  {"tick_size": 0.25,   "tick_value": 12.50,  "multiplier": 50},
    "ZS":  {"tick_size": 0.25,   "tick_value": 12.50,  "multiplier": 50},
    "MZC": {"tick_size": 0.50,   "tick_value": 2.50,   "multiplier": 5},
    "MZW": {"tick_size": 0.50,   "tick_value": 2.50,   "multiplier": 5},
    "MZS": {"tick_size": 0.50,   "tick_value": 2.50,   "multiplier": 5},
}


# ---------------------------------------------------------------------------
# Annexe A — Coûts de transaction (COMM_RT + SLIP_RT, Round-Trip)
# Convention : RT = entrée + sortie incluses. Appliqué UNE SEULE FOIS par trade.
# ---------------------------------------------------------------------------

class CostSpec(TypedDict):
    comm_rt: float   # commission round-trip en $
    slip_rt: float   # slippage round-trip en $ (= 2 ticks)


COSTS_RT: dict[str, CostSpec] = {
    "NQ":  {"comm_rt": 3.80,  "slip_rt": 10.00},
    "ES":  {"comm_rt": 3.80,  "slip_rt": 25.00},
    "RTY": {"comm_rt": 3.80,  "slip_rt": 10.00},
    "YM":  {"comm_rt": 3.80,  "slip_rt": 10.00},
    "MNQ": {"comm_rt": 1.24,  "slip_rt": 1.00},
    "MYM": {"comm_rt": 1.24,  "slip_rt": 1.00},
    "MES": {"comm_rt": 1.24,  "slip_rt": 2.50},
    "M2K": {"comm_rt": 1.24,  "slip_rt": 1.00},
    "CL":  {"comm_rt": 4.00,  "slip_rt": 20.00},
    "NG":  {"comm_rt": 4.20,  "slip_rt": 20.00},
    "BZ":  {"comm_rt": 2.60,  "slip_rt": 20.00},
    "HO":  {"comm_rt": 4.00,  "slip_rt": 8.40},
    "RB":  {"comm_rt": 4.00,  "slip_rt": 8.40},
    "MCL": {"comm_rt": 1.54,  "slip_rt": 2.00},
    "QG":  {"comm_rt": 1.54,  "slip_rt": 25.00},
    "GC":  {"comm_rt": 4.20,  "slip_rt": 20.00},
    "SI":  {"comm_rt": 4.20,  "slip_rt": 50.00},
    "HG":  {"comm_rt": 4.20,  "slip_rt": 25.00},
    "PL":  {"comm_rt": 4.20,  "slip_rt": 10.00},
    "PA":  {"comm_rt": 4.20,  "slip_rt": 100.00},
    "MGC": {"comm_rt": 1.70,  "slip_rt": 2.00},
    "SIL": {"comm_rt": 2.50,  "slip_rt": 10.00},
    "MHG": {"comm_rt": 1.70,  "slip_rt": 2.50},
    "ZC":  {"comm_rt": 5.30,  "slip_rt": 25.00},
    "ZW":  {"comm_rt": 5.30,  "slip_rt": 25.00},
    "ZS":  {"comm_rt": 5.30,  "slip_rt": 25.00},
    "MZC": {"comm_rt": 1.54,  "slip_rt": 5.00},
    "MZW": {"comm_rt": 1.54,  "slip_rt": 5.00},
    "MZS": {"comm_rt": 1.54,  "slip_rt": 5.00},
}


# ---------------------------------------------------------------------------
# Price Type par actif — Section 3.1 du V1
# Close pour actifs liquides, Typical Price (H+L+C)/3 pour actifs moins liquides.
# Décision prise une fois en étape 1, propagée partout.
# ---------------------------------------------------------------------------

PRICE_TYPE: dict[str, str] = {
    "ES":  "close",    "NQ":  "close",    "CL":  "close",
    "NG":  "close",    "QG":  "close",    "GC":  "close",    "HO":  "close",
    "RTY": "close",    "RB":  "close",    "BZ":  "close",
    "ZC":  "close",    "ZW":  "close",    "ZS":  "close",
    "SI":  "typical",  "YM":  "close",    "HG":  "typical",
    "PL":  "typical",  "PA":  "typical",
}


# ---------------------------------------------------------------------------
# Seuil low_liquidity_day — Section 3.1 Table 2 du V1
# Volume jour < seuil → exclure de calibration (étapes 2-4).
# ---------------------------------------------------------------------------

LOW_LIQ_PCT: dict[str, float] = {
    # HIGH liquidity : 30% de la médiane
    "ES": 0.30, "NQ": 0.30, "CL": 0.30, "NG": 0.30, "GC": 0.30,
    "HO": 0.30, "RTY": 0.30, "RB": 0.30, "BZ": 0.30, "ZC": 0.30,
    "ZW": 0.30, "ZS": 0.30,
    # MID liquidity : 30% de la médiane
    "SI": 0.30, "YM": 0.30, "HG": 0.30, "PL": 0.30, "QG": 0.30,
    # LOW liquidity : 50% de la médiane
    "PA": 0.50,
}


# ---------------------------------------------------------------------------
# Annexe B — Q_Kalman par classe (V1 — table fixe)
# Q_Kalman = diag(q_α, q_β) — covariance bruit d'état [α_t, β_t]
# NE PAS confondre avec Q_OU (variance conditionnelle du spread).
# ---------------------------------------------------------------------------

Q_KALMAN: dict[str, tuple[float, float]] = {
    "Metals":       (1e-6, 1e-7),   # GC/SI, GC/PA
    "Equity Index": (2e-6, 2e-7),   # NQ/RTY
    "Grains":       (2e-6, 2e-7),   # ZC/ZW
    "Energy":       (5e-6, 5e-7),   # CL/HO, CL/NG
}


# ---------------------------------------------------------------------------
# Mapping Standard → Micro
# ---------------------------------------------------------------------------

MICRO_MAP: dict[str, str | None] = {
    "GC": "MGC",  "SI": "SIL",  "HG": "MHG",
    "NQ": "MNQ",  "YM": "MYM",  "ES": "MES",
    "RTY": "M2K",
    "CL": "MCL",  "NG": "QG",
    "ZC": "MZC",  "ZW": "MZW",  "ZS": "MZS",
    "HO": None,   "RB": None,
    "PA": None,   "PL": None,   "BZ": None,
}


def find_micro(symbol: str) -> str | None:
    """Retourne le symbole micro correspondant, ou None."""
    return MICRO_MAP.get(symbol)


# ---------------------------------------------------------------------------
# Configuration des 6 paires
# ---------------------------------------------------------------------------

class PairConfig(TypedDict):
    leg_a: str
    leg_b: str
    classe: str
    rollover_excl: int      # sessions à exclure par leg autour du roll
    t_close_pit: str | None  # contrainte pit close (CT), None = 15:30


PAIRS: dict[str, PairConfig] = {
    "GC_SI": {
        "leg_a": "GC", "leg_b": "SI", "classe": "Metals",
        "rollover_excl": 3, "t_close_pit": None,
    },
    "GC_PA": {
        "leg_a": "GC", "leg_b": "PA", "classe": "Metals",
        "rollover_excl": 3, "t_close_pit": None,
    },
    "NQ_RTY": {
        "leg_a": "NQ", "leg_b": "RTY", "classe": "Equity Index",
        "rollover_excl": 0, "t_close_pit": None,
    },
    "CL_HO": {
        "leg_a": "CL", "leg_b": "HO", "classe": "Energy",
        "rollover_excl": 1, "t_close_pit": None,
    },
    "CL_NG": {
        "leg_a": "CL", "leg_b": "NG", "classe": "Energy",
        "rollover_excl": 1, "t_close_pit": None,
    },
    "ZC_ZW": {
        "leg_a": "ZC", "leg_b": "ZW", "classe": "Grains",
        "rollover_excl": 1, "t_close_pit": "13:20",
    },
}


# ---------------------------------------------------------------------------
# Annexe C — Valeurs critiques MacKinnon (résidus régression bivariée)
# Pour test AR(1) étape 3 uniquement — pas étape 2.
# ---------------------------------------------------------------------------

MACKINNON_CV: dict[str, dict[str, float]] = {
    # N ≈ 2640 (10j)
    "10d": {"1%": -3.96, "5%": -3.37, "10%": -3.07},
    # N ≈ 7920 (30j)
    "30d": {"1%": -3.93, "5%": -3.35, "10%": -3.06},
    # N ≈ 15840 (60j)
    "60d": {"1%": -3.92, "5%": -3.34, "10%": -3.05},
}


# ---------------------------------------------------------------------------
# Session CME
# ---------------------------------------------------------------------------

SESSION_OPEN_CT = "17:30"    # ouverture session
SESSION_CLOSE_CT = "15:30"   # clôture session
TRADER_START_CT = "01:00"    # 08h00 FR = 01h00 CT
