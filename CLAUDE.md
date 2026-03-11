# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Backtesting pipeline for mean-reversion spread trading on CME futures.
Intraday 5min bars. Manual trading. OLS/OU calibration + dynamic Kalman filter.
6 pairs: GC/SI, GC/PA, NQ/RTY, CL/HO, CL/NG, ZC/ZW.

## Source of Truth

The spec is `docs/recherche/modele_cointegration_v1_FINAL.docx`. All formulas, thresholds, and conventions come from this document. Never improvise a formula or parameter.

## Commands

```bash
# Activate venv (Windows/Git Bash)
source venv/Scripts/activate

# Run a single module
python src/step1_data.py

# Run tests
python -m pytest tests/
python -m pytest tests/test_step1.py         # single test file
python -m pytest tests/test_step1.py -k "test_name"  # single test

# Install dependencies
pip install pandas numpy statsmodels scipy matplotlib
```

## Architecture

The pipeline is a linear sequence of modules, each reading the output of the previous one:

```
data/raw/*.csv (Sierra Chart 1min)
    → src/step1_data.py        : session split, flags, 5min aggregation
    → src/step2_stationarity.py: ADF+KPSS tests, downsampling, multi-scale
    → src/step3_cointegration.py: OLS, AR(1), MacKinnon, β stability
    → src/step4_ou.py          : κ, σ_eq, half-life, OU parameter estimation
    → src/step5_engine.py      : Kalman filter, NIS, state machine (phases 1-3)
    → src/step5_risk.py        : risk filters A/B/C (phase 4)
    → src/step5_sizing.py      : beta-neutral sizing, multipliers (phase 5)
    → src/backtester.py        : full backtest loop, anti-look-ahead, PnL, Sharpe
```

Config tables (contract specs, commissions, Kalman Q) go in `config/`.
Each module is testable in isolation with `if __name__ == '__main__'`.

## Python Conventions

- Python 3.10+, functional style (pure functions, no classes unless necessary)
- Type hints required on all functions
- Docstrings with inputs/outputs on every function

## Critical Rules (The 7 Prohibitions)

1. **No `df.resample()` without `groupby('session_id')`** — creates phantom overnight bars
2. **Never use σ_diffusion as Z-score denominator** — thresholds wrong by ~3x, use σ_eq
3. **Use `multiplier` for notional, not `tick_value`** — sizing wrong by ~10x
4. **Never pass Q_OU as Q_Kalman** — filter explodes
5. **Use Joseph form for P update: `P = (I-KH)P_pred(I-KH)' + KRK'`** — plain form is numerically unstable
6. **Use MacKinnon critical values for DF test, not standard** — standard gives false positives
7. **`spread_cost_rt` applied once per trade, not twice** — avoid double-counting fees

## Time Conventions

- `dt = 1` (one 5min bar) everywhere. No annualization. κ in bars, half-life in bars × 5min.
- CME session: open 17:30 CT, close 15:30 CT. Trader active from 01:00 CT (08:00 FR).
- ZC/ZW: pit close at 13:20 CT.

## Data

- Source: Sierra Chart CSV exports, 1min bars, continuous contract (Volume Based + Back Adjusted additive)
- Raw data in `data/raw/`, processed in `data/processed/` — both gitignored
- Outputs in `outputs/` — also gitignored
