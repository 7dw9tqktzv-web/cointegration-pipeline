"""
Runner — Backtest V2.1 sigma_rolling.

Phase 1 : ZC/ZW × 3 fenêtres (20, 40, 60)
Phase 2 : 7 paires × meilleure fenêtre

Usage: python run_backtest_v2.py
"""
import io
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.step1_data import run_step1
from src.backtester import run_backtest
from config.contracts import PAIRS

# Mapping symbole -> fichier raw
RAW = ROOT / "data" / "raw"
FILE_MAP = {
    "GC":  RAW / "GCJ26_FUT_CME.scid_BarData.txt",
    "SI":  RAW / "SIK26_FUT_CME.scid_BarData.txt",
    "PA":  RAW / "PAM26_FUT_CME.scid_BarData.txt",
    "NQ":  RAW / "NQH26_FUT_CME.scid_BarData.txt",
    "RTY": RAW / "RTYH26_FUT_CME.scid_BarData.txt",
    "YM":  RAW / "YMH26_FUT_CME.scid_BarData.txt",
    "CL":  RAW / "CLJ26_FUT_CME.scid_BarData.txt",
    "HO":  RAW / "HOJ26_FUT_CME.scid_BarData.txt",
    "NG":  RAW / "NGJ26_FUT_CME.scid_BarData.txt",
    "ZC":  RAW / "ZCK26_FUT_CME.scid_BarData.txt",
    "ZW":  RAW / "ZWK26_FUT_CME.scid_BarData.txt",
}

PAIR_ORDER = ["GC_SI", "GC_PA", "NQ_RTY", "YM_RTY", "CL_HO", "CL_NG", "ZC_ZW"]
WINDOWS = [20, 40, 60]

# Cache step1
step1_cache: dict = {}
_devnull = io.StringIO()


def get_step1(symbol: str):
    if symbol not in step1_cache:
        with redirect_stdout(_devnull):
            step1_cache[symbol] = run_step1(FILE_MAP[symbol], symbol)
    return step1_cache[symbol]


def run_pair(pair_name: str, window: int) -> dict:
    cfg = PAIRS[pair_name]
    sym_a, sym_b = cfg["leg_a"], cfg["leg_b"]
    df_a = get_step1(sym_a)
    df_b = get_step1(sym_b)
    return run_backtest(df_a, df_b, sym_a, sym_b, pair_name,
                        verbose=False, sigma_rolling_window=window)


def print_result_line(pair_name: str, window: int, r: dict, elapsed: float):
    n_trades = len([t for t in r['trades'] if t.get('exit_timestamp')])
    m = r['metrics']

    # Exit motif breakdown
    completed = [t for t in r['trades'] if t.get('exit_motif')]
    tp = sum(1 for t in completed if t['exit_motif'] == 'TAKE_PROFIT')
    sl = sum(1 for t in completed if t['exit_motif'] == 'STOP_LOSS')
    sc = sum(1 for t in completed if t['exit_motif'] == 'SESSION_CLOSE')
    sf = sum(1 for t in completed if t['exit_motif'] == 'SORTIE_FORCEE')

    sharpe_str = f"{m['sharpe_1x']:+.2f}" if n_trades > 0 else "  n/a"
    wr_str = f"{m['win_rate']:.0%}" if n_trades > 0 else "n/a"

    print(f"  {pair_name:<10} w={window:<3} | "
          f"{r['n_sessions_traded']:>4}/{r['n_sessions_total']:<4} traded | "
          f"{n_trades:>4} trades | "
          f"TP={tp} SL={sl} SC={sc} SF={sf} | "
          f"Sharpe={sharpe_str} WR={wr_str} | "
          f"{elapsed:.0f}s")


if __name__ == "__main__":
    print("=" * 85)
    print("  BACKTEST V2.1 — sigma_rolling")
    print("=" * 85)

    # ---------------------------------------------------------------
    # PHASE 1 : ZC/ZW × 3 fenêtres
    # ---------------------------------------------------------------
    print(f"\n--- PHASE 1 : ZC/ZW × fenêtres {WINDOWS} ---")
    print(f"Start: {time.strftime('%H:%M:%S')}\n")

    phase1_results = {}
    for w in WINDOWS:
        t0 = time.time()
        r = run_pair("ZC_ZW", w)
        elapsed = time.time() - t0
        phase1_results[w] = r
        print_result_line("ZC_ZW", w, r, elapsed)

    # Choisir la meilleure fenêtre (Sharpe_1x, puis nombre de trades)
    best_window = max(WINDOWS, key=lambda w: (
        phase1_results[w]['metrics']['sharpe_1x'],
        phase1_results[w]['metrics']['n_total'],
    ))
    print(f"\n  -> Meilleure fenêtre : {best_window} barres "
          f"(Sharpe={phase1_results[best_window]['metrics']['sharpe_1x']:+.2f})")

    # ---------------------------------------------------------------
    # PHASE 2 : 7 paires × meilleure fenêtre
    # ---------------------------------------------------------------
    print(f"\n--- PHASE 2 : 7 paires × window={best_window} ---")
    print(f"Start: {time.strftime('%H:%M:%S')}\n")

    phase2_results = {}
    for pair_name in PAIR_ORDER:
        t0 = time.time()
        r = run_pair(pair_name, best_window)
        elapsed = time.time() - t0
        phase2_results[pair_name] = r
        print_result_line(pair_name, best_window, r, elapsed)

    # ---------------------------------------------------------------
    # TABLEAU RÉCAPITULATIF
    # ---------------------------------------------------------------
    print(f"\n{'=' * 85}")
    print(f"  RÉCAPITULATIF V2.1 — window={best_window}")
    print(f"{'=' * 85}")
    print(f"{'Paire':<10} {'Traded':>12} {'Trades':>7} {'TP':>4} {'SL':>4} "
          f"{'SC':>4} {'SF':>4} {'Sharpe':>8} {'WR':>6} {'W/L':>6} {'MaxDD':>10}")
    print("-" * 85)

    for pair_name in PAIR_ORDER:
        r = phase2_results[pair_name]
        m = r['metrics']
        completed = [t for t in r['trades'] if t.get('exit_motif')]
        tp = sum(1 for t in completed if t['exit_motif'] == 'TAKE_PROFIT')
        sl = sum(1 for t in completed if t['exit_motif'] == 'STOP_LOSS')
        sc = sum(1 for t in completed if t['exit_motif'] == 'SESSION_CLOSE')
        sf = sum(1 for t in completed if t['exit_motif'] == 'SORTIE_FORCEE')
        n_trades = m['n_total']

        if n_trades > 0:
            print(f"{pair_name:<10} "
                  f"{r['n_sessions_traded']:>4}/{r['n_sessions_total']:<6} "
                  f"{n_trades:>7} {tp:>4} {sl:>4} {sc:>4} {sf:>4} "
                  f"{m['sharpe_1x']:>+8.2f} {m['win_rate']:>5.0%} "
                  f"{m['win_loss_ratio']:>6.1f} {m['max_dd_dollars']:>10.0f}")
        else:
            print(f"{pair_name:<10} "
                  f"{r['n_sessions_traded']:>4}/{r['n_sessions_total']:<6} "
                  f"{n_trades:>7} {tp:>4} {sl:>4} {sc:>4} {sf:>4} "
                  f"{'n/a':>8} {'n/a':>6} {'n/a':>6} {'n/a':>10}")

    # Skip reasons
    print(f"\n--- Skip reasons ---")
    for pair_name in PAIR_ORDER:
        r = phase2_results[pair_name]
        if r['skip_reasons']:
            print(f"  {pair_name}: {r['skip_reasons']}")

    # Robustesse slippage
    print(f"\n--- Robustesse slippage ---")
    for pair_name in PAIR_ORDER:
        m = phase2_results[pair_name]['metrics']
        if m['n_total'] > 0:
            print(f"  {pair_name}: Sharpe_1x={m['sharpe_1x']:+.2f} "
                  f"Sharpe_1.5x={m['sharpe_1_5x']:+.2f} "
                  f"Sharpe_2x={m['sharpe_2x']:+.2f}")

    print(f"\nEnd: {time.strftime('%H:%M:%S')}")
