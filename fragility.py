"""
fragility.py — Fragility tests for Variant B (55/10/2.0)
1. Leave-one-out
2. Crypto-only vs ETF-only
3. Walk-forward by year
4. Slippage/fees sensitivity
"""
import sys
sys.path.insert(0, '/Users/robwilson/Desktop/leapfrog-research')

import backtest as bt
from backtest import run, VARIANTS

# Set final params
VARIANTS["B"]["entry_days"] = 55
VARIANTS["B"]["exit_days"]  = 10
bt.ATR_STOP_MULT             = 2.0
bt.RISK_PER_TRADE            = 0.005  # 0.5%

BASE     = ["BTC-USD", "ETH-USD", "SOL-USD", "GLD", "QQQ"]
IN_S     = "2018-01-01";  IN_E  = "2021-12-31"
OOS_S    = "2022-01-01";  OOS_E = "2025-06-01"

def summary(label, r_in, r_oos):
    print(f"  {label:35s}  "
          f"IS: CAGR={r_in['cagr_pct']:+5.1f}% SR={r_in['sharpe']:.2f} DD={r_in['max_drawdown_pct']:5.1f}%  |  "
          f"OOS: CAGR={r_oos['cagr_pct']:+5.1f}% SR={r_oos['sharpe']:.2f} DD={r_oos['max_drawdown_pct']:5.1f}% PF={r_oos['profit_factor']:.2f}")

# ── 1. Leave-one-out ──────────────────────────────────────────────────────────
print(f"\n{'='*110}")
print(f"  TEST 1: LEAVE-ONE-OUT")
print(f"{'='*110}")
r_base_in  = run("B", BASE, IN_S, IN_E,  label="baseline", verbose=False)
r_base_oos = run("B", BASE, OOS_S, OOS_E, label="baseline", verbose=False)
summary("BASELINE (all 5)", r_base_in, r_base_oos)
print()
for drop in BASE:
    subset = [t for t in BASE if t != drop]
    r_in  = run("B", subset, IN_S, IN_E,  label=f"drop {drop}", verbose=False)
    r_oos = run("B", subset, OOS_S, OOS_E, label=f"drop {drop}", verbose=False)
    oos_sr_diff = r_oos["sharpe"] - r_base_oos["sharpe"]
    flag = " ⚠ FRAGILE" if r_oos["sharpe"] < 0.7 or oos_sr_diff < -0.3 else ""
    summary(f"  drop {drop}", r_in, r_oos)
    print(f"    {'':35s}  OOS Sharpe change: {oos_sr_diff:+.3f}{flag}")

# ── 2. Crypto-only vs ETF-only ────────────────────────────────────────────────
print(f"\n{'='*110}")
print(f"  TEST 2: CRYPTO-ONLY vs ETF-ONLY")
print(f"{'='*110}")
universes = {
    "BTC + ETH + SOL only":  ["BTC-USD", "ETH-USD", "SOL-USD"],
    "BTC + ETH only":        ["BTC-USD", "ETH-USD"],
    "GLD + QQQ only":        ["GLD", "QQQ"],
    "Extended ETFs":         ["SPY", "QQQ", "GLD", "IWM", "EFA"],
}
for label, tickers in universes.items():
    r_in  = run("B", tickers, IN_S, IN_E,  label=label, verbose=False)
    r_oos = run("B", tickers, OOS_S, OOS_E, label=label, verbose=False)
    summary(label, r_in, r_oos)

# ── 3. Walk-forward by year ───────────────────────────────────────────────────
print(f"\n{'='*110}")
print(f"  TEST 3: WALK-FORWARD BY YEAR")
print(f"{'='*110}")
print(f"  {'Year':6s}  {'CAGR':>8s}  {'Sharpe':>7s}  {'MaxDD':>7s}  {'PF':>6s}  {'Trades':>7s}  {'P&L $':>8s}")
print(f"  {'-'*6}  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*6}  {'-'*7}  {'-'*8}")
years = range(2019, 2026)
for yr in years:
    try:
        r = run("B", BASE, f"{yr}-01-01", f"{yr}-12-31", label=str(yr), verbose=False)
        pnl = r["final_equity"] - bt.STARTING_CAPITAL
        flag = " ★" if r["sharpe"] > 0.8 else (" ✗" if r["sharpe"] < 0 else "")
        print(f"  {yr:6d}  {r['cagr_pct']:>7.1f}%  {r['sharpe']:>7.3f}  "
              f"{r['max_drawdown_pct']:>7.1f}%  {r['profit_factor']:>6.2f}  "
              f"{r['n_trades']:>7d}  ${pnl:>+8.0f}{flag}")
    except Exception as e:
        print(f"  {yr:6d}  ERROR: {e}")

# ── 4. Slippage/fee sensitivity ───────────────────────────────────────────────
print(f"\n{'='*110}")
print(f"  TEST 4: SLIPPAGE/FEE SENSITIVITY (OOS only)")
print(f"{'='*110}")
print(f"  {'Crypto slip':12s}  {'ETF slip':10s}  {'OOS CAGR':>9s}  {'OOS Sharpe':>11s}  {'OOS DD':>7s}  {'OOS PF':>7s}")
print(f"  {'-'*12}  {'-'*10}  {'-'*9}  {'-'*11}  {'-'*7}  {'-'*7}")
slip_combos = [
    (0.0005, 0.0001),  # baseline (current)
    (0.001,  0.001),   # realistic IB
    (0.0025, 0.001),   # moderate
    (0.005,  0.001),   # high crypto
    (0.01,   0.002),   # worst case
]
for c_slip, e_slip in slip_combos:
    bt.SLIPPAGE_CRYPTO = c_slip
    bt.SLIPPAGE_EQUITY = e_slip
    r = run("B", BASE, OOS_S, OOS_E, label="slip", verbose=False)
    flag = " ⚠" if r["sharpe"] < 0.7 else ""
    print(f"  {c_slip*100:.2f}%{'':8s}  {e_slip*100:.2f}%{'':6s}  "
          f"{r['cagr_pct']:>8.1f}%  {r['sharpe']:>11.3f}  "
          f"{r['max_drawdown_pct']:>7.1f}%  {r['profit_factor']:>7.2f}{flag}")

# Reset to defaults
bt.SLIPPAGE_CRYPTO = 0.0005
bt.SLIPPAGE_EQUITY = 0.001

print(f"\n{'='*110}")
print(f"  FRAGILITY SUMMARY")
print(f"{'='*110}")
print(f"  Baseline OOS: CAGR={r_base_oos['cagr_pct']:+.1f}%  Sharpe={r_base_oos['sharpe']:.3f}  DD={r_base_oos['max_drawdown_pct']:.1f}%")
print(f"  Run complete.")
