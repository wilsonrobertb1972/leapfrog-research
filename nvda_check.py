"""
nvda_check.py — Does NVDA belong in the paper universe?
Tests the exact paper trader strategy (25/8/2.0x ATR breakout) on:
  - NVDA alone
  - ETH alone  (what it replaced)
  - QQQ alone  (what it replaced)
  - Paper universe:     BTC + SOL + NVDA + GLD
  - Validated universe: BTC + SOL + ETH  + GLD + QQQ

IS:  2018-01-01 → 2021-12-31
OOS: 2022-01-01 → 2025-06-01
"""

import numpy as np
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

# ── Strategy params (identical to paper_trader.py) ────────────────────────────
ENTRY_DAYS   = 25
EXIT_DAYS    = 8
ATR_PERIOD   = 20
ATR_MULT     = 2.0
RISK_PCT     = 0.0025
MAX_POSITIONS = 2          # kept conservative for fair comparison
SLIPPAGE     = 0.001
COMMISSION   = 1.0
START_CAP    = 10_000.0

# ── Data fetch (reuses data.py if available, else raw yfinance) ───────────────
def get_bars(ticker: str, start: str, end: str) -> pd.DataFrame:
    try:
        from data import get_daily
        df = get_daily(ticker, start, end)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    import yfinance as yf
    raw = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [c.lower() for c in raw.columns]
    raw.index = pd.to_datetime(raw.index)
    return raw[["open","high","low","close","volume"]]

# ── Core backtest ──────────────────────────────────────────────────────────────
def run_backtest(tickers: list[str], start: str, end: str,
                 max_pos: int = MAX_POSITIONS) -> dict:
    data = {}
    for t in tickers:
        df = get_bars(t, start, end)
        if df is not None and not df.empty:
            data[t] = df
        else:
            print(f"  [warn] no data for {t}")

    if not data:
        return {}

    # ── FIX: normalise all indices to tz-naive before aligning ────────────────
    for t in list(data.keys()):
        df = data[t].copy()
        idx = pd.to_datetime(df.index)
        if idx.tz is not None:
            idx = idx.tz_convert(None)
        df.index = idx
        data[t] = df
    # ──────────────────────────────────────────────────────────────────────────

    closes = pd.DataFrame({t: data[t]["close"] for t in data if t in data})
    opens  = pd.DataFrame({t: data[t]["open"]  for t in data if t in data})
    closes = closes.dropna(how="all")
    opens  = opens.reindex(closes.index)

    equity    = START_CAP
    positions = {}
    trades    = []
    eq_curve  = []

    for i in range(max(ENTRY_DAYS + 1, ATR_PERIOD + 1), len(closes)):
        today_date  = closes.index[i]
        prev_closes = closes.iloc[:i]
        today_open  = opens.iloc[i]

        to_close = []
        for t, pos in positions.items():
            if t not in closes.columns:
                continue
            pc = closes.iloc[i-1][t]
            if pd.isna(pc):
                continue
            ex_low = prev_closes[t].iloc[-(EXIT_DAYS+1):-1].min()
            if pc < ex_low or pc <= pos["stop"]:
                fill = today_open[t] * (1 - SLIPPAGE) if not pd.isna(today_open[t]) else pc
                pnl  = (fill - pos["entry_price"]) * pos["shares"] - COMMISSION
                equity += pos["cost"] + pnl
                equity  = max(equity, 0.01)
                reason  = "8d-low" if pc < ex_low else "ATR-stop"
                trades.append({"ticker": t, "pnl": pnl, "reason": reason,
                               "entry": pos["entry_price"], "exit": fill,
                               "date": today_date})
                to_close.append(t)
        for t in to_close:
            del positions[t]

        if len(positions) < max_pos:
            for t in closes.columns:
                if t in positions:
                    continue
                if len(positions) >= max_pos:
                    break
                pc = closes.iloc[i-1][t]
                if pd.isna(pc):
                    continue
                high_n = prev_closes[t].iloc[-(ENTRY_DAYS+1):-1].max()
                if pc <= high_n:
                    continue
                cl = prev_closes[t].iloc[-ATR_PERIOD-1:].dropna()
                trs = [abs(cl.iloc[j] - cl.iloc[j-1]) for j in range(1, len(cl))]
                atr = float(np.mean(trs)) if trs else 0.0
                if atr <= 0:
                    continue
                fill = today_open[t] * (1 + SLIPPAGE) if not pd.isna(today_open[t]) else pc * 1.001
                stop = fill - ATR_MULT * atr
                risk = fill - stop
                if risk <= 0:
                    continue
                shares = (equity * RISK_PCT) / risk
                cost   = fill * shares + COMMISSION
                if cost > equity * 0.90:
                    shares = (equity * 0.90 - COMMISSION) / fill
                    cost   = fill * shares + COMMISSION
                if shares <= 0 or cost > equity:
                    continue
                equity -= cost
                positions[t] = {"shares": shares, "entry_price": fill,
                                 "stop": stop, "cost": cost}

        open_pnl = 0.0
        for t, pos in positions.items():
            px = closes.iloc[i][t] if t in closes.columns else pos["entry_price"]
            if pd.isna(px):
                px = pos["entry_price"]
            open_pnl += (px - pos["entry_price"]) * pos["shares"]
        eq_curve.append(equity + open_pnl)

    if not eq_curve:
        return {}

    eq_s   = pd.Series(eq_curve)
    rets   = eq_s.pct_change().dropna()
    n_days = len(eq_s)
    years  = n_days / 252
    cagr   = (eq_s.iloc[-1] / START_CAP) ** (1 / years) - 1 if years > 0 else 0
    sharpe = (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0
    dd     = (eq_s / eq_s.cummax() - 1).min()
    wins   = sum(1 for t in trades if t["pnl"] > 0)
    gross_w = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_l = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    pf     = gross_w / gross_l if gross_l > 0 else float("inf")
    total_pnl = sum(t["pnl"] for t in trades)

    return {
        "trades": len(trades), "win_rate": wins/len(trades)*100 if trades else 0,
        "cagr": cagr, "sharpe": sharpe, "max_dd": dd, "pf": pf,
        "total_pnl": total_pnl, "final_eq": eq_s.iloc[-1],
        "trade_list": trades,
    }

# ── Report helper ──────────────────────────────────────────────────────────────
def fmt(r: dict) -> str:
    if not r:
        return "  no data"
    return (f"  CAGR={r['cagr']:+.1%}  Sharpe={r['sharpe']:.2f}  "
            f"DD={r['max_dd']:.1%}  PF={r['pf']:.2f}  "
            f"Trades={r['trades']}  WR={r['win_rate']:.0f}%  "
            f"P&L=${r['total_pnl']:+,.0f}")

IS_START,  IS_END  = "2018-01-01", "2021-12-31"
OOS_START, OOS_END = "2022-01-01", "2025-06-01"

def section(label, tickers, max_pos=MAX_POSITIONS):
    print(f"\n{'─'*65}")
    print(f"  {label}")
    print(f"{'─'*65}")
    r_is  = run_backtest(tickers, IS_START,  IS_END,  max_pos)
    r_oos = run_backtest(tickers, OOS_START, OOS_END, max_pos)
    print(f"  IS  (2018–2021): {fmt(r_is)}")
    print(f"  OOS (2022–2025): {fmt(r_oos)}")
    return r_is, r_oos

print("\n" + "="*65)
print("  NVDA vs ETH vs QQQ — 25/8/2.0x breakout strategy check")
print("="*65)

section("NVDA alone",  ["NVDA"],    max_pos=1)
section("ETH alone",   ["ETH-USD"], max_pos=1)
section("QQQ alone",   ["QQQ"],     max_pos=1)

section("Paper universe:     BTC + SOL + NVDA + GLD",
        ["BTC-USD","SOL-USD","NVDA","GLD"], max_pos=2)
section("Validated universe: BTC + SOL + ETH + GLD + QQQ",
        ["BTC-USD","SOL-USD","ETH-USD","GLD","QQQ"], max_pos=2)

print("\n" + "="*65)
print("  Done.")
print("="*65 + "\n")
