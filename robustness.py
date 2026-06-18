"""
robustness.py — Parameter robustness grid for Variant B
Tests entry/exit breakout days and ATR stop multiplier.
A robust strategy shows a PLATEAU not a spike.
"""
import sys, itertools
sys.path.insert(0, '/Users/robwilson/Desktop/leapfrog-research')

import pandas as pd
from backtest import run, VARIANTS, STARTING_CAPITAL

TICKERS   = ["BTC-USD", "ETH-USD", "SOL-USD", "GLD", "QQQ"]
IN_START  = "2018-01-01";  IN_END  = "2021-12-31"
OOS_START = "2022-01-01";  OOS_END = "2025-06-01"

# Parameter grid
ENTRY_DAYS = [30, 40, 45, 50, 55, 60, 65, 70, 80]
EXIT_DAYS  = [10, 15, 20, 25, 30]
ATR_MULTS  = [1.5, 2.0, 2.5, 3.0]

rows = []
total = len(ENTRY_DAYS) * len(EXIT_DAYS) * len(ATR_MULTS)
done  = 0

print(f"Running {total} combinations... (this takes a few minutes)")

for entry_n, exit_n, atr_m in itertools.product(ENTRY_DAYS, EXIT_DAYS, ATR_MULTS):
    if exit_n >= entry_n:
        continue  # exit must be shorter than entry

    # Temporarily patch variant B
    VARIANTS["B"]["entry_days"] = entry_n
    VARIANTS["B"]["exit_days"]  = exit_n

    # Also patch ATR multiplier in backtest module
    import backtest as bt
    bt.ATR_STOP_MULT = atr_m

    try:
        r_in  = run("B", TICKERS, IN_START,  IN_END,  label="IS",  verbose=False)
        r_oos = run("B", TICKERS, OOS_START, OOS_END, label="OOS", verbose=False)
        rows.append({
            "entry": entry_n,
            "exit":  exit_n,
            "atr":   atr_m,
            "IS_cagr":   r_in["cagr_pct"],
            "IS_sharpe": r_in["sharpe"],
            "IS_dd":     r_in["max_drawdown_pct"],
            "OOS_cagr":  r_oos["cagr_pct"],
            "OOS_sharpe":r_oos["sharpe"],
            "OOS_dd":    r_oos["max_drawdown_pct"],
            "OOS_pf":    r_oos["profit_factor"],
            "OOS_trades":r_oos["n_trades"],
        })
    except Exception as e:
        pass

    done += 1
    if done % 10 == 0:
        print(f"  {done}/{total} done...")

df = pd.DataFrame(rows)
df = df.sort_values("OOS_sharpe", ascending=False)

print(f"\n{'='*90}")
print(f"  ROBUSTNESS GRID — Variant B — OOS sorted by Sharpe")
print(f"  Universe: {', '.join(TICKERS)}")
print(f"{'='*90}")
print(f"  {'Entry':>5}  {'Exit':>5}  {'ATR':>4}  {'IS CAGR':>8}  {'IS SR':>6}  {'OOS CAGR':>9}  {'OOS SR':>7}  {'OOS DD':>7}  {'OOS PF':>7}  {'Trd':>4}")
print(f"  {'-'*5}  {'-'*5}  {'-'*4}  {'-'*8}  {'-'*6}  {'-'*9}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*4}")
for _, r in df.head(20).iterrows():
    mark = " ★" if r["OOS_sharpe"] >= 0.8 and r["OOS_dd"] >= -20 and r["OOS_pf"] >= 3 else ""
    print(f"  {r['entry']:>5}  {r['exit']:>5}  {r['atr']:>4.1f}  "
          f"{r['IS_cagr']:>7.1f}%  {r['IS_sharpe']:>6.3f}  "
          f"{r['OOS_cagr']:>8.1f}%  {r['OOS_sharpe']:>7.3f}  "
          f"{r['OOS_dd']:>7.1f}%  {r['OOS_pf']:>7.2f}  {r['OOS_trades']:>4.0f}{mark}")

# Show distribution of OOS Sharpe to check for plateau vs spike
print(f"\n  OOS Sharpe distribution across all {len(df)} valid combos:")
bins = [0, 0.3, 0.5, 0.7, 0.9, 1.1, 99]
labels = ["< 0.3", "0.3–0.5", "0.5–0.7", "0.7–0.9", "0.9–1.1", "> 1.1"]
for i, (lo, hi) in enumerate(zip(bins, bins[1:])):
    count = ((df["OOS_sharpe"] >= lo) & (df["OOS_sharpe"] < hi)).sum()
    bar = "█" * count
    print(f"    {labels[i]:10s} {bar} ({count})")

# Best baseline params
best = df.iloc[0]
print(f"\n  Best combo: entry={best['entry']:.0f}d / exit={best['exit']:.0f}d / ATR={best['atr']:.1f}x")
print(f"  OOS: CAGR={best['OOS_cagr']:+.1f}%  Sharpe={best['OOS_sharpe']:.3f}  DD={best['OOS_dd']:.1f}%  PF={best['OOS_pf']:.2f}")
print(f"\n  Our baseline (55/20/2.0x):")
baseline = df[(df["entry"]==55) & (df["exit"]==20) & (df["atr"]==2.0)]
if len(baseline):
    b = baseline.iloc[0]
    print(f"  OOS: CAGR={b['OOS_cagr']:+.1f}%  Sharpe={b['OOS_sharpe']:.3f}  DD={b['OOS_dd']:.1f}%  PF={b['OOS_pf']:.2f}")
    rank = df.index.get_loc(baseline.index[0]) + 1
    print(f"  Rank: #{rank} of {len(df)}")
