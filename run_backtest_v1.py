"""
Runner — Backtest V1 sur les 7 paires avec données 3 ans.
Usage: python run_backtest_v1.py
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

# Mapping symbole → fichier raw
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

# Cache step1 pour ne pas recharger le même actif 2 fois
step1_cache: dict = {}
_devnull = io.StringIO()


def get_step1(symbol: str):
    if symbol not in step1_cache:
        with redirect_stdout(_devnull):
            step1_cache[symbol] = run_step1(FILE_MAP[symbol], symbol)
    return step1_cache[symbol]


if __name__ == "__main__":
    results = {}
    print(f"Backtest V1 — 7 paires, 3 ans, s2_refresh=10")
    print(f"Start: {time.strftime('%H:%M:%S')}\n")

    for pair_name in PAIR_ORDER:
        cfg = PAIRS[pair_name]
        sym_a, sym_b = cfg["leg_a"], cfg["leg_b"]

        t0 = time.time()
        sys.stdout.write(f"  {pair_name} ({sym_a}/{sym_b}) ... ")
        sys.stdout.flush()

        df_a = get_step1(sym_a)
        df_b = get_step1(sym_b)

        result = run_backtest(df_a, df_b, sym_a, sym_b, pair_name, verbose=False)
        elapsed = time.time() - t0

        results[pair_name] = result

        n_trades = len([t for t in result['trades'] if t.get('exit_timestamp')])
        print(f"done {elapsed:.0f}s | "
              f"{result['n_sessions_traded']}/{result['n_sessions_total']} traded | "
              f"{n_trades} trades | {result['skip_reasons']}")

    # Tableau final
    print(f"\n{'='*80}")
    print("  TABLEAU RÉCAPITULATIF — BACKTEST V1 (3 ans)")
    print(f"{'='*80}")
    print(f"{'Paire':<10} {'Sessions':>8} {'Traded':>7} {'Trades':>7} {'Blocage principal':<35}")
    print("-" * 75)
    for pair_name in PAIR_ORDER:
        r = results[pair_name]
        n_trades = len([t for t in r['trades'] if t.get('exit_timestamp')])
        # Tous les motifs de blocage
        if r['skip_reasons']:
            top_reason = max(r['skip_reasons'], key=r['skip_reasons'].get)
            top_count = r['skip_reasons'][top_reason]
            motif = f"{top_reason} ({top_count})"
        else:
            motif = "-"
        print(f"{pair_name:<10} {r['n_sessions_total']:>8} {r['n_sessions_traded']:>7} "
              f"{n_trades:>7} {motif:<35}")

    # Détail skip reasons
    print(f"\n--- Détail skip reasons ---")
    for pair_name in PAIR_ORDER:
        r = results[pair_name]
        print(f"  {pair_name}: {r['skip_reasons']}")

    # Métriques si trades > 0
    has_trades = any(
        len([t for t in results[p]['trades'] if t.get('exit_timestamp')]) > 0
        for p in PAIR_ORDER
    )
    if has_trades:
        print(f"\n--- Métriques ---")
        for pair_name in PAIR_ORDER:
            r = results[pair_name]
            m = r['metrics']
            if m['n_total'] > 0:
                print(f"  {pair_name}: Sharpe={m['sharpe_1x']:.2f} | "
                      f"WR={m['win_rate']:.1%} | "
                      f"W/L={m['win_loss_ratio']:.1f} | "
                      f"MaxDD=${m['max_dd_dollars']:.0f} | "
                      f"Forced={m['forced_rate']:.0%}")

    print(f"\nEnd: {time.strftime('%H:%M:%S')}")
