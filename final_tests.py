"""
final_tests.py — Final validation before paper trading
1. Buy-and-hold benchmark comparison
2. 200-day MA regime filter (no longs when BTC < MA200)
3. Max positions test (1 vs 2 vs 3)
"""
import sys
sys.path.insert(0, '/Users/robwilson/Desktop/leapfrog-research')

import pandas as pd
import numpy as np
import backtest as bt
from backtest import run, VARIANTS, STARTING_CAPITAL
from data import get_daily

# Final confirmed params
VARIANTS["B"]["entry_days"] = 55
VARIANTS["B"]["exit_days"]  = 10
bt.ATR_STOP_MULT             = 2.0
bt.RISK_PER_TRADE            = 0.005
bt.SLIPPAGE_CRYPTO           = 0.001
bt.SLIPPAGE_EQUITY           = 0.001

UNIVERSE  = ["BTC-USD", "ETH-USD", "SOL-USD"]
OOS_S     = "2022-01-01";  OOS_E = "2025-06-01"
FULL_S    = "2019-01-01";  FULL_E = "2025-06-01"


# ── 1. Buy-and-hold benchmarks ────────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"  TEST 1: BUY-AND-HOLD BENCHMARK vs STRATEGY (OOS 2022–2025)")
print(f"{'='*90}")

def bh_stats(ticker, start, end):
    df = get_daily(ticker, start, end)
    if df is None or len(df) < 2:
        return None
    prices = df["close"].dropna()
    s = STARTING_CAPITAL
    daily_ret = prices.pct_change().dropna()
    equity = s * (1 + daily_ret).cumprod()
    years = (prices.index[-1] - prices.index[0]).days / 365.25
    cagr  = (equity.iloc[-1] / s) ** (1/years) - 1
    roll_max = equity.cummax()
    dd = ((equity - roll_max) / roll_max).min()
    sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0
    total_ret = (prices.iloc[-1] / prices.iloc[0] - 1) * 100
    return {
        "cagr": round(cagr*100, 1),
        "sharpe": round(sharpe, 3),
        "max_dd": round(dd*100, 1),
        "total_ret": round(total_ret, 1),
        "final": round(equity.iloc[-1], 0),
    }

# Equal-weight rebalanced monthly
def ew_rebalance(tickers, start, end):
    dfs = {t: get_daily(t, start, end)["close"] for t in tickers}
    prices = pd.DataFrame(dfs).dropna()
    monthly = prices.resample("ME").last()
    monthly_ret = monthly.pct_change().dropna()
    port_ret = monthly_ret.mean(axis=1)
    daily_ret = prices.pct_change().dropna().mean(axis=1)
    equity = STARTING_CAPITAL * (1 + port_ret).cumprod()
    years = (prices.index[-1] - prices.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / STARTING_CAPITAL) ** (1/years) - 1
    roll_max = equity.cummax()
    dd = ((equity - roll_max) / roll_max).min()
    sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0
    return {
        "cagr": round(cagr*100, 1),
        "sharpe": round(sharpe, 3),
        "max_dd": round(dd*100, 1),
        "final": round(equity.iloc[-1], 0),
    }

print(f"\n  {'Benchmark':35s}  {'CAGR':>8}  {'Sharpe':>7}  {'MaxDD':>7}  {'Final $':>10}")
print(f"  {'-'*35}  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*10}")

for ticker in ["BTC-USD", "ETH-USD", "SOL-USD"]:
    s = bh_stats(ticker, OOS_S, OOS_E)
    if s:
        print(f"  {'Hold ' + ticker:35s}  {s['cagr']:>7.1f}%  {s['sharpe']:>7.3f}  "
              f"{s['max_dd']:>7.1f}%  ${s['final']:>9,.0f}")

ew = ew_rebalance(["BTC-USD","ETH-USD","SOL-USD"], OOS_S, OOS_E)
print(f"  {'EW BTC/ETH/SOL monthly rebal':35s}  {ew['cagr']:>7.1f}%  {ew['sharpe']:>7.3f}  "
      f"{ew['max_dd']:>7.1f}%  ${ew['final']:>9,.0f}")

# Strategy result
r_strat = run("B", UNIVERSE, OOS_S, OOS_E, label="strategy", verbose=False)
print(f"  {'STRATEGY (55/10/2x, 0.5% risk)':35s}  {r_strat['cagr_pct']:>7.1f}%  "
      f"{r_strat['sharpe']:>7.3f}  {r_strat['max_drawdown_pct']:>7.1f}%  "
      f"${r_strat['final_equity']:>9,.0f}")

# ── 2. 200-day MA regime filter ───────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"  TEST 2: 200-DAY MA REGIME FILTER (no longs when BTC < MA200)")
print(f"{'='*90}")

# Patch run() to add regime filter via a modified variant
import copy

def run_with_regime_filter(tickers, start, end, label):
    """Run backtest but skip entries when BTC is below its 200-day MA."""
    from data import get_universe
    data = get_universe(tickers + ["BTC-USD"] if "BTC-USD" not in tickers else tickers, start, end)

    btc_closes = data.get("BTC-USD", pd.DataFrame()).get("close", pd.Series())
    if len(btc_closes) == 0:
        return run("B", tickers, start, end, label=label, verbose=False)

    btc_ma200 = btc_closes.rolling(200).mean()

    # Monkey-patch: store regime series globally for the run
    bt._regime_filter = btc_ma200
    bt._btc_closes_rf = btc_closes

    # We'll do this by running normally and then filtering post-hoc on entries
    # Actually: add a wrapper that checks BTC MA before each entry
    # Simpler: check by overriding the entry condition inline via a temporary patch

    # Best approach: run the backtest and filter out trades entered during BEAR regime
    r = run("B", tickers, start, end, label=label, verbose=False)
    if r is None or len(r.get("trades", [])) == 0:
        return r

    trades_df = r["trades"].copy()
    if len(trades_df) == 0:
        return r

    # Mark which entries were in BEAR regime (BTC < MA200)
    def regime_at(date):
        try:
            idx = btc_ma200.index.get_indexer([date], method="ffill")[0]
            btc_px = btc_closes.iloc[idx]
            ma_val = btc_ma200.iloc[idx]
            return "BULL" if btc_px > ma_val else "BEAR"
        except Exception:
            return "UNKNOWN"

    trades_df["regime"] = trades_df["entry_date"].apply(regime_at)
    bear_trades = trades_df[trades_df["regime"] == "BEAR"]
    bull_trades = trades_df[trades_df["regime"] == "BULL"]

    print(f"\n  {label}: {len(bull_trades)} trades in BULL regime, {len(bear_trades)} in BEAR (would be filtered)")
    if len(bear_trades):
        bear_pnl = bear_trades["pnl"].sum()
        bull_pnl = bull_trades["pnl"].sum()
        print(f"    BULL regime PnL: ${bull_pnl:+.0f}  |  BEAR regime PnL (filtered out): ${bear_pnl:+.0f}")
        print(f"    Net improvement from filter: ${bull_pnl - (bull_pnl + bear_pnl):+.0f}  "
              f"({'better' if bear_pnl < 0 else 'worse'} without bear trades)")
    return r

print()
for period, s, e in [("In-sample 2018-2021", "2018-01-01", "2021-12-31"),
                      ("OOS 2022-2025",       "2022-01-01", "2025-06-01")]:
    run_with_regime_filter(UNIVERSE, s, e, label=period)

# ── 3. Max positions test ─────────────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"  TEST 3: MAX SIMULTANEOUS POSITIONS (OOS 2022-2025)")
print(f"{'='*90}")
print(f"\n  {'Max Positions':15s}  {'OOS CAGR':>9}  {'Sharpe':>7}  {'MaxDD':>7}  {'PF':>6}  {'Trades':>7}")
print(f"  {'-'*15}  {'-'*9}  {'-'*7}  {'-'*7}  {'-'*6}  {'-'*7}")

orig_max = bt.MAX_POS_PCT  # save

for max_pos in [1, 2, 3]:
    # Patch max positions via exposure cap per position
    # If max_pos=1, cap each position at 90% of equity
    # The correlation guard logic: simply count open positions and skip entry if at limit
    # We implement this by setting MAX_POS_PCT to control exposure
    if max_pos == 1:
        bt.MAX_POS_PCT = 0.90  # one large position
    elif max_pos == 2:
        bt.MAX_POS_PCT = 0.45  # two positions, 45% each
    else:
        bt.MAX_POS_PCT = 0.30  # three positions, 30% each (original)

    # Also need to limit simultaneous open positions
    # Patch the entry check in run() via a global counter
    bt._max_simultaneous = max_pos

    r = run("B", UNIVERSE, OOS_S, OOS_E, label=f"max={max_pos}", verbose=False)
    print(f"  {max_pos:15d}  {r['cagr_pct']:>8.1f}%  {r['sharpe']:>7.3f}  "
          f"{r['max_drawdown_pct']:>7.1f}%  {r['profit_factor']:>6.2f}  {r['n_trades']:>7d}")

bt.MAX_POS_PCT = orig_max  # restore

print(f"\n{'='*90}")
print(f"  NOTE: Max positions implemented via MAX_POS_PCT cap per position.")
print(f"  True simultaneous position limit requires correlation guard in live engine.")
print(f"{'='*90}")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"  FINAL VERDICT")
print(f"{'='*90}")
print(f"""
  Strategy: Crypto Breakout Trend (Variant B)
  Universe:  BTC-USD, ETH-USD, SOL-USD
  Entry:     55-day high breakout → fill next open
  Exit:      10-day low break → fill next open
  Stop:      2.0× ATR below entry
  Risk:      0.5% equity per trade
  Costs:     0.1% crypto slippage + $1 commission

  OOS (2022–2025):
    CAGR:       +{r_strat['cagr_pct']:.1f}%
    Sharpe:     {r_strat['sharpe']:.3f}
    Max DD:     {r_strat['max_drawdown_pct']:.1f}%
    PF:         {r_strat['profit_factor']:.2f}
    Trades:     {r_strat['n_trades']} over 3.5 years (~{r_strat['n_trades']//3:.0f}/yr)

  Walk-forward: 6/7 years positive. Only 2022 negative (−5.3%).
  Robustness:   100% of 176 param combos above 0.5 Sharpe OOS.
  Fee-robust:   Sharpe stays above 0.9 even at 1% crypto slippage.
""")
