import sys
sys.path.insert(0, '/Users/robwilson/Desktop/leapfrog-research')
from vix_breakout import run_vix_backtest
import itertools

TICKERS = ["NVDA", "GLD", "BTC-USD", "SOL-USD"]
OOS_S   = "2022-01-01";  OOS_E = "2025-06-01"
IN_S    = "2018-01-01";  IN_E  = "2021-12-31"

ENTRY_DAYS = [15, 20, 25, 30, 40]
EXIT_DAYS  = [5, 8, 10, 15, 20]
ATR_MULTS  = [1.5, 2.0, 2.5, 3.0]

import backtest as bt
rows = []
total = len(ENTRY_DAYS) * len(EXIT_DAYS) * len(ATR_MULTS)
done = 0
print(f"Running {total} combinations...")

for entry_n, exit_n, atr_m in itertools.product(ENTRY_DAYS, EXIT_DAYS, ATR_MULTS):
    if exit_n >= entry_n:
        continue
    bt.ATR_STOP_MULT = atr_m
    # patch entry/exit into vix_breakout module
    import vix_breakout as vb
    vb.ENTRY_N = entry_n
    vb.EXIT_N  = exit_n
    vb.ATR_MULT = atr_m
    try:
        r_in  = run_vix_backtest(TICKERS, IN_S,  IN_E,  None, label="IS")
        r_oos = run_vix_backtest(TICKERS, OOS_S, OOS_E, None, label="OOS")
        rows.append({
            "entry": entry_n, "exit": exit_n, "atr": atr_m,
            "IS_sr":  r_in["sharpe"],
            "OOS_sr": r_oos["sharpe"],
            "OOS_dd": r_oos["max_dd_pct"],
            "OOS_pf": r_oos["profit_factor"],
            "OOS_tr": r_oos["trades_per_year"],
            "OOS_cagr": r_oos["cagr_pct"],
        })
    except Exception as e:
        pass
    done += 1
    if done % 15 == 0:
        print(f"  {done}/{total}...")

import pandas as pd
df = pd.DataFrame(rows).sort_values("OOS_sr", ascending=False)

print(f"\n{'='*95}")
print(f"  ROBUSTNESS GRID — NVDA+GLD+BTC+SOL — OOS sorted by Sharpe")
print(f"{'='*95}")
print(f"  {'Entry':>5}  {'Exit':>5}  {'ATR':>4}  {'IS SR':>6}  {'OOS SR':>7}  {'OOS DD':>7}  {'OOS PF':>7}  {'Tr/yr':>6}  {'OOS CAGR':>9}")
print(f"  {'-'*5}  {'-'*5}  {'-'*4}  {'-'*6}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*6}  {'-'*9}")
for _, r in df.head(20).iterrows():
    mark = " ★" if r["OOS_sr"] >= 1.2 and r["OOS_dd"] >= -20 else ""
    print(f"  {r['entry']:>5.0f}  {r['exit']:>5.0f}  {r['atr']:>4.1f}  "
          f"{r['IS_sr']:>6.3f}  {r['OOS_sr']:>7.3f}  {r['OOS_dd']:>7.1f}%  "
          f"{r['OOS_pf']:>7.2f}  {r['OOS_tr']:>6.1f}  {r['OOS_cagr']:>8.1f}%{mark}")

# Distribution
print(f"\n  OOS Sharpe distribution ({len(df)} valid combos):")
bins   = [0, 0.5, 0.7, 0.9, 1.1, 1.3, 99]
labels = ["< 0.5","0.5–0.7","0.7–0.9","0.9–1.1","1.1–1.3","> 1.3"]
for i, (lo, hi) in enumerate(zip(bins, bins[1:])):
    n = ((df["OOS_sr"] >= lo) & (df["OOS_sr"] < hi)).sum()
    print(f"    {labels[i]:10s} {'█'*n} ({n})")

best = df.iloc[0]
base = df[(df["entry"]==20) & (df["exit"]==10) & (df["atr"]==2.0)]
print(f"\n  Best combo: {best['entry']:.0f}/{best['exit']:.0f}/{best['atr']:.1f}x  OOS SR={best['OOS_sr']:.3f}  DD={best['OOS_dd']:.1f}%")
if len(base):
    b = base.iloc[0]
    rank = list(df.index).index(base.index[0]) + 1
    print(f"  Baseline 20/10/2x: OOS SR={b['OOS_sr']:.3f}  DD={b['OOS_dd']:.1f}%  Rank #{rank}/{len(df)}")
