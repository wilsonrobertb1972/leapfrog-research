import sys
sys.path.insert(0, '/Users/robwilson/Desktop/leapfrog-research')
from vix_breakout import run_vix_backtest

UNIVERSES = {
    "NVDA+BTC+SOL":           ["NVDA", "BTC-USD", "SOL-USD"],
    "NVDA+BTC+ETH+SOL":       ["NVDA", "BTC-USD", "ETH-USD", "SOL-USD"],
    "NVDA+QQQ+BTC+SOL":       ["NVDA", "QQQ", "BTC-USD", "SOL-USD"],
    "NVDA+GLD+BTC+SOL":       ["NVDA", "GLD", "BTC-USD", "SOL-USD"],
    "Crypto-only (baseline)":  ["BTC-USD", "ETH-USD", "SOL-USD"],
}

IN_S="2018-01-01"; IN_E="2021-12-31"
OOS_S="2022-01-01"; OOS_E="2025-06-01"

print(f"\n{'='*110}")
print(f"  NVDA + CRYPTO UNIVERSE TEST — 20/10/2x")
print(f"{'='*110}")
print(f"\n  {'Universe':30s}  {'IS SR':>6}  |  {'OOS CAGR':>9}  {'OOS SR':>7}  {'OOS DD':>7}  {'OOS PF':>6}  {'Tr/yr':>6}")
print(f"  {'-'*30}  {'-'*6}  |  {'-'*9}  {'-'*7}  {'-'*7}  {'-'*6}  {'-'*6}")

best_oos = None
for name, tickers in UNIVERSES.items():
    r_in  = run_vix_backtest(tickers, IN_S,  IN_E,  None, label=name)
    r_oos = run_vix_backtest(tickers, OOS_S, OOS_E, None, label=name)
    flag  = " ★" if r_oos["sharpe"] >= 1.1 and r_oos["trades_per_year"] >= 20 else ""
    print(f"  {name:30s}  {r_in['sharpe']:>6.3f}  |  "
          f"{r_oos['cagr_pct']:>8.1f}%  {r_oos['sharpe']:>7.3f}  "
          f"{r_oos['max_dd_pct']:>7.1f}%  {r_oos['profit_factor']:>6.2f}  "
          f"{r_oos['trades_per_year']:>6.1f}{flag}")
    if flag and (best_oos is None or r_oos["sharpe"] > best_oos[2]["sharpe"]):
        best_oos = (name, tickers, r_oos)

if best_oos:
    name, tickers, r = best_oos
    print(f"\n  Best: {name}")
    print(f"  P&L by ticker (OOS):")
    for tkr, s in sorted(r["by_ticker"].items(), key=lambda x: -x[1]["pnl"]):
        print(f"    {tkr:10s}  ${s['pnl']:>+8.0f}  {s['trades']:3d}tr  win%={s['win_rate']:.0f}")
    print(f"\n  Walk-forward by year:")
    print(f"  {'Year':6s}  {'Sharpe':>7}  {'Trades':>7}  {'P&L':>8}")
    for yr in range(2019, 2026):
        try:
            r2 = run_vix_backtest(tickers, f"{yr}-01-01", f"{yr}-12-31", None, label=str(yr))
            pnl = r2["final_equity"] - 10000
            flag2 = " ★" if r2["sharpe"] > 0.8 else (" ✗" if pnl < 0 else "")
            print(f"  {yr:6d}  {r2['sharpe']:>7.3f}  {r2['n_trades']:>7d}  ${pnl:>+8.0f}{flag2}")
        except Exception as e:
            print(f"  {yr}: ERROR {e}")

print(f"\n  Baseline (55/10 BTC+ETH+SOL): OOS SR=1.267 DD=-6.9% Tr/yr=12")
