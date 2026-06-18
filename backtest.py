"""
backtest.py — Multi-asset trend following backtest engine
leapfrog-research

Strategy variants (test all, pick the robust one):
  A. Turtle short : 20-day breakout entry, 10-day low exit
  B. Turtle long  : 55-day breakout entry, 20-day low exit
  C. MA200 cross  : enter above 200-day MA, exit below
  D. Momentum 12m : enter if 12-month return > 0, exit if < 0

Position sizing: risk-based (1% equity per trade), ATR stop.
Fill: next-day open (no look-ahead).
Costs: 0.1% slippage equities / 0.05% crypto + $1 commission.

Usage:
  from backtest import run
  results = run("A", ["SPY","GLD","BTC-USD","ETH-USD"], "2018-01-01", "2023-12-31")
  results = run("A", [...], "2018-01-01", "2021-12-31", label="in-sample")
  results = run("A", [...], "2022-01-01", "2023-12-31", label="out-of-sample")
"""

import numpy as np
import pandas as pd
from tabulate import tabulate
from data import get_universe

# ── Config ─────────────────────────────────────────────────────────────────────
STARTING_CAPITAL  = 10_000.0   # USD
RISK_PER_TRADE    = 0.01       # 1% of equity per trade
MAX_POS_PCT       = 0.30       # max 30% of portfolio in one asset
ATR_STOP_MULT     = 2.0        # stop = entry - 2×ATR
ATR_PERIOD        = 20
SLIPPAGE_EQUITY   = 0.001      # 0.1%
SLIPPAGE_CRYPTO   = 0.0005     # 0.05%
COMMISSION        = 1.0        # $1 per trade (IB-style)

_CRYPTO_TICKERS = {"BTC-USD","ETH-USD","SOL-USD","AVAX-USD",
                   "LINK-USD","XRP-USD","DOGE-USD","ADA-USD"}

VARIANTS = {
    "A": {"entry_days": 20, "exit_days": 10,  "mode": "breakout"},
    "B": {"entry_days": 55, "exit_days": 20,  "mode": "breakout"},
    "C": {"ma_period":  200,                   "mode": "ma_cross"},
    "D": {"lookback":   252,                   "mode": "momentum"},
}


# ── Main entry point ───────────────────────────────────────────────────────────
def run(
    variant:   str,
    tickers:   list[str],
    start:     str,
    end:       str,
    label:     str = "backtest",
    long_only: bool = True,
    verbose:   bool = True,
) -> dict:
    """Run a full backtest. Returns results dict with equity curve and stats."""
    cfg = VARIANTS[variant]
    data = get_universe(tickers, start, end)
    if not data:
        print("No data loaded.")
        return {}

    # Align all series to common trading dates
    closes = pd.DataFrame({t: data[t]["close"] for t in data}).dropna(how="all")
    opens  = pd.DataFrame({t: data[t]["open"]  for t in data}).dropna(how="all")

    equity   = STARTING_CAPITAL
    positions = {}   # ticker → {shares, entry_price, stop, atr}
    trades   = []
    equity_curve = []

    for i in range(1, len(closes)):
        today      = closes.index[i]
        prev_close = closes.iloc[i-1]
        today_open = opens.iloc[i]

        # ── 1. Check exits on open ────────────────────────────────────────────
        for ticker in list(positions.keys()):
            if ticker not in closes.columns:
                continue
            pos   = positions[ticker]
            price = today_open.get(ticker, np.nan)
            if np.isnan(price):
                continue

            exit_signal = False
            exit_reason = ""

            if cfg["mode"] == "breakout":
                exit_n  = cfg["exit_days"]
                low_n   = closes[ticker].iloc[max(0,i-1-exit_n):i-1].min()
                if prev_close[ticker] < low_n:
                    exit_signal = True
                    exit_reason = f"{exit_n}d low break"
            elif cfg["mode"] == "ma_cross":
                ma_p   = cfg["ma_period"]
                ma_val = closes[ticker].iloc[max(0,i-ma_p):i].mean()
                if prev_close[ticker] < ma_val:
                    exit_signal = True
                    exit_reason = f"price < MA{ma_p}"
            elif cfg["mode"] == "momentum":
                lb    = cfg["lookback"]
                if i >= lb:
                    ret = closes[ticker].iloc[i] / closes[ticker].iloc[i-lb] - 1
                    if ret < 0:
                        exit_signal = True
                        exit_reason = f"12m return negative"

            # Hard ATR stop
            if price <= pos["stop"]:
                exit_signal = True
                exit_reason = "ATR stop"

            if exit_signal:
                if price != price: continue  # skip NaN price
                slip   = SLIPPAGE_CRYPTO if ticker in _CRYPTO_TICKERS else SLIPPAGE_EQUITY
                fill   = price * (1 - slip)
                pnl    = (fill - pos["entry_price"]) * pos["shares"] - COMMISSION
                equity += pos.get("cost", fill * pos["shares"]) + pnl
                if equity != equity: equity = 0.01  # NaN guard
                trades.append({
                    "ticker":      ticker,
                    "entry_date":  pos["entry_date"],
                    "exit_date":   today,
                    "entry_price": round(pos["entry_price"], 4),
                    "exit_price":  round(fill, 4),
                    "shares":      round(pos["shares"], 4),
                    "pnl":         round(pnl, 2),
                    "pnl_pct":     round((fill / pos["entry_price"] - 1) * 100, 2),
                    "exit_reason": exit_reason,
                    "hold_days":   (today - pos["entry_date"]).days,
                })
                del positions[ticker]

        # ── 2. Check entries ───────────────────────────────────────────────────
        for ticker in closes.columns:
            if ticker in positions:
                continue
            if len(positions) >= len(closes.columns):
                continue

            price = today_open.get(ticker, np.nan)
            if np.isnan(price) or price <= 0:
                continue

            entry_signal = False

            if cfg["mode"] == "breakout":
                entry_n  = cfg["entry_days"]
                if i < entry_n:
                    continue
                high_n   = closes[ticker].iloc[max(0,i-1-entry_n):i-1].max()
                if prev_close[ticker] > high_n:
                    entry_signal = True
            elif cfg["mode"] == "ma_cross":
                ma_p   = cfg["ma_period"]
                if i < ma_p + 1:
                    continue
                ma_now  = closes[ticker].iloc[max(0,i-ma_p):i].mean()
                ma_prev = closes[ticker].iloc[max(0,i-ma_p-1):i-1].mean()
                if prev_close[ticker] > ma_now and closes[ticker].iloc[i-2] <= ma_prev:
                    entry_signal = True
            elif cfg["mode"] == "momentum":
                lb    = cfg["lookback"]
                if i < lb:
                    continue
                ret = closes[ticker].iloc[i-1] / closes[ticker].iloc[i-1-lb] - 1
                if ret > 0 and (i < lb+1 or
                    (closes[ticker].iloc[i-2] / closes[ticker].iloc[i-2-lb] - 1) <= 0):
                    entry_signal = True

            if not entry_signal:
                continue

            # ATR for stop and sizing
            atr = _atr(closes[ticker], i, ATR_PERIOD)
            if atr <= 0:
                continue
            stop = price - ATR_STOP_MULT * atr

            # Position size: risk 1% of equity
            risk_amt  = equity * RISK_PER_TRADE
            risk_unit = price - stop
            if risk_unit <= 0:
                continue
            shares = risk_amt / risk_unit

            # Cap at MAX_POS_PCT of equity
            max_shares = (equity * MAX_POS_PCT) / price
            shares = min(shares, max_shares)
            if shares <= 0:
                continue

            slip = SLIPPAGE_CRYPTO if ticker in _CRYPTO_TICKERS else SLIPPAGE_EQUITY
            fill = price * (1 + slip)
            cost = fill * shares + COMMISSION

            if cost > equity * 0.95:
                continue

            equity -= (fill * shares + COMMISSION)
            positions[ticker] = {
                "shares":      shares,
                "entry_price": fill,
                "entry_date":  today,
                "stop":        stop,
                "atr":         atr,
                "cost":        fill * shares + COMMISSION,
            }

        # ── 3. Mark-to-market equity ──────────────────────────────────────────
        open_val = 0.0
        for t, pos in positions.items():
            if t in closes.columns:
                px = closes.iloc[i][t]
                px = px if not (px != px) else pos["entry_price"]  # NaN guard
                open_val += px * pos["shares"]
        equity_curve.append({"date": today, "equity": max(equity + open_val, 0.01)})

    # ── Close any remaining positions at final close ───────────────────────────
    final_close = closes.iloc[-1]
    for ticker, pos in positions.items():
        price = final_close.get(ticker, pos["entry_price"])
        if price != price: price = pos["entry_price"]  # NaN guard
        slip  = SLIPPAGE_CRYPTO if ticker in _CRYPTO_TICKERS else SLIPPAGE_EQUITY
        fill  = price * (1 - slip)
        pnl   = (fill - pos["entry_price"]) * pos["shares"] - COMMISSION
        equity += pos.get("cost", fill * pos["shares"]) + pnl
        trades.append({
            "ticker":      ticker,
            "entry_date":  pos["entry_date"],
            "exit_date":   closes.index[-1],
            "entry_price": round(pos["entry_price"], 4),
            "exit_price":  round(fill, 4),
            "shares":      round(pos["shares"], 4),
            "pnl":         round(pnl, 2),
            "pnl_pct":     round((fill / pos["entry_price"] - 1) * 100, 2),
            "exit_reason": "end_of_test",
            "hold_days":   (closes.index[-1] - pos["entry_date"]).days,
        })

    equity_curve.append({"date": closes.index[-1], "equity": equity})

    # ── Stats ─────────────────────────────────────────────────────────────────
    results = _compute_stats(trades, equity_curve, label, variant, tickers, start, end)

    if verbose:
        _print_report(results)

    return results


# ── Stats ──────────────────────────────────────────────────────────────────────
def _compute_stats(trades, equity_curve, label, variant, tickers, start, end) -> dict:
    df_eq = pd.DataFrame(equity_curve).set_index("date")["equity"]
    df_tr = pd.DataFrame(trades) if trades else pd.DataFrame()

    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    final = df_eq.iloc[-1] if len(df_eq) else STARTING_CAPITAL
    cagr  = (final / STARTING_CAPITAL) ** (1 / years) - 1 if years > 0 and final > 0 else 0

    # Drawdown
    rolling_max = df_eq.cummax()
    drawdown    = (df_eq - rolling_max) / rolling_max
    max_dd      = drawdown.min()
    # Time underwater (days with drawdown > 0)
    underwater_days = (drawdown < -0.001).sum()

    # Daily returns for Sharpe
    daily_ret = df_eq.pct_change().dropna()
    sharpe    = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0
    sortino_d = daily_ret[daily_ret < 0].std()
    sortino   = (daily_ret.mean() / sortino_d * np.sqrt(252)) if sortino_d > 0 else 0

    if len(df_tr):
        n_trades    = len(df_tr)
        n_wins      = (df_tr["pnl"] > 0).sum()
        win_rate    = n_wins / n_trades
        avg_win     = df_tr[df_tr["pnl"] > 0]["pnl"].mean() if n_wins else 0
        avg_loss    = df_tr[df_tr["pnl"] <= 0]["pnl"].mean() if (n_trades - n_wins) else 0
        gross_prof  = df_tr[df_tr["pnl"] > 0]["pnl"].sum()
        gross_loss  = abs(df_tr[df_tr["pnl"] <= 0]["pnl"].sum()) or 1
        pf          = gross_prof / gross_loss
        avg_trade   = df_tr["pnl"].mean()
        avg_hold    = df_tr["hold_days"].mean()
        worst_20    = df_tr.nsmallest(20, "pnl")[["ticker","entry_date","exit_date","pnl","exit_reason"]]
        # By year
        df_tr["year"] = pd.to_datetime(df_tr["exit_date"]).dt.year
        by_year     = df_tr.groupby("year")["pnl"].sum().to_dict()
    else:
        n_trades = n_wins = 0
        win_rate = avg_win = avg_loss = gross_prof = pf = avg_trade = avg_hold = 0
        worst_20 = pd.DataFrame()
        by_year  = {}

    by_ticker = {}
    if len(df_tr):
        for tkr, grp in df_tr.groupby("ticker"):
            wins = (grp["pnl"] > 0).sum()
            by_ticker[tkr] = {"trades": len(grp), "total_pnl": round(grp["pnl"].sum(),2), "avg_trade": round(grp["pnl"].mean(),2), "win_rate": round(wins/len(grp)*100,1)}
    return {
        "label": label, "variant": variant, "tickers": tickers, "by_ticker": by_ticker,
        "start": start, "end": end,
        "starting_capital": STARTING_CAPITAL,
        "final_equity": round(final, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "underwater_days": int(underwater_days),
        "n_trades": n_trades,
        "win_rate_pct": round(win_rate * 100, 1),
        "profit_factor": round(pf, 3),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_trade": round(avg_trade, 2),
        "avg_hold_days": round(avg_hold, 1),
        "by_year": by_year,
        "worst_20": worst_20,
        "equity_curve": df_eq,
        "trades": pd.DataFrame(trades) if trades else pd.DataFrame(),
    }


def _print_report(r: dict):
    print(f"\n{'='*60}")
    print(f"  {r['label'].upper()} — Variant {r['variant']} — {r['start']} to {r['end']}")
    print(f"  Tickers: {', '.join(r['tickers'])}")
    print(f"{'='*60}")
    stats = [
        ["CAGR",            f"{r['cagr_pct']:+.1f}%"],
        ["Sharpe",           f"{r['sharpe']:.3f}"],
        ["Sortino",          f"{r['sortino']:.3f}"],
        ["Max Drawdown",     f"{r['max_drawdown_pct']:.1f}%"],
        ["Days Underwater",  f"{r['underwater_days']}"],
        ["Profit Factor",    f"{r['profit_factor']:.3f}"],
        ["Win Rate",         f"{r['win_rate_pct']:.1f}%"],
        ["Avg Win",          f"${r['avg_win']:.2f}"],
        ["Avg Loss",         f"${r['avg_loss']:.2f}"],
        ["Avg Trade",        f"${r['avg_trade']:.2f}"],
        ["Avg Hold (days)",  f"{r['avg_hold_days']:.1f}"],
        ["Total Trades",     f"{r['n_trades']}"],
        ["Final Equity",     f"${r['final_equity']:,.2f}"],
    ]
    print(tabulate(stats, tablefmt="simple"))
    if r["by_year"]:
        print(f"\n  P&L by year:")
        for yr, pnl in sorted(r["by_year"].items()):
            bar = "█" * int(abs(pnl)/50) if abs(pnl) > 0 else ""
            print(f"    {yr}: ${pnl:+8.0f}  {bar}")
    if len(r["worst_20"]):
        print(f"\n  Worst 5 trades:")
        print(r["worst_20"].head(5).to_string(index=False))
    if "by_ticker" in r and r["by_ticker"]:
        print(f"\n  P&L by ticker:")
        for tkr, s in sorted(r["by_ticker"].items(), key=lambda x: -x[1]["total_pnl"]):
            sign = "+" if s["total_pnl"] >= 0 else ""
            print(f'    {tkr:12s} {sign}${s["total_pnl"]:>8.0f}  {s["trades"]:3d}tr  win%={s["win_rate"]:.0f}')
    print()


# ── ATR helper ─────────────────────────────────────────────────────────────────
def _atr(series: pd.Series, idx: int, period: int) -> float:
    window = series.iloc[max(0, idx-period):idx]
    if len(window) < 2:
        return 0.0
    return float(window.diff().abs().mean())


# ── Run all variants ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    TICKERS  = ["SPY", "GLD", "QQQ", "TLT", "BTC-USD", "ETH-USD"]
    IN_START  = "2018-01-01"
    IN_END    = "2021-12-31"
    OOS_START = "2022-01-01"
    OOS_END   = "2025-06-01"

    print("\n── IN-SAMPLE (2018–2021) ─────────────────────────────────────")
    for v in ["A","B","C","D"]:
        run(v, TICKERS, IN_START, IN_END, label=f"in-sample")

    print("\n── OUT-OF-SAMPLE (2022–2025) ─────────────────────────────────")
    for v in ["A","B","C","D"]:
        run(v, TICKERS, OOS_START, OOS_END, label=f"out-of-sample")
