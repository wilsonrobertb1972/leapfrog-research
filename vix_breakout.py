"""
vix_breakout.py — 20-day breakout with VIX regime filter
Tests whether adding a VIX threshold increases signal frequency
and improves risk-adjusted returns vs the plain 55/10 system.

Hypothesis: breakouts in high-VIX regimes (trending) produce better
returns than breakouts in low-VIX regimes (grinding/choppy).

Universe: SPY, QQQ, GLD, BTC-USD, NVDA
VIX thresholds tested: no filter, >12, >15, >18, >20
Entry lookbacks tested: 20-day (higher frequency)
"""
import sys
sys.path.insert(0, '/Users/robwilson/Desktop/leapfrog-research')

import numpy as np
import pandas as pd
from tabulate import tabulate
from data import get_daily, get_universe
import backtest as bt
from backtest import VARIANTS, STARTING_CAPITAL, _atr, SLIPPAGE_CRYPTO, SLIPPAGE_EQUITY, COMMISSION, _CRYPTO_TICKERS, MAX_POS_PCT, RISK_PER_TRADE

# ── Config ─────────────────────────────────────────────────────────────────────
UNIVERSE  = ["SPY", "QQQ", "GLD", "BTC-USD", "NVDA"]
IN_S      = "2018-01-01";  IN_E  = "2021-12-31"
OOS_S     = "2022-01-01";  OOS_E = "2025-06-01"

ENTRY_N   = 20
EXIT_N    = 10
ATR_MULT  = 2.0
RISK_PCT  = 0.005   # 0.5%

# ── VIX data ──────────────────────────────────────────────────────────────────
def get_vix(start, end):
    """Fetch VIX from Yahoo Finance."""
    df = get_daily("^VIX", start, end)
    if df is None or len(df) == 0:
        print("[warn] VIX data unavailable — trying VXX as proxy")
        df = get_daily("VXX", start, end)
    return df["close"] if df is not None and len(df) > 0 else None

# ── Core backtest with VIX filter ─────────────────────────────────────────────
def run_vix_backtest(tickers, start, end, vix_min=None, label=""):
    """
    Run 20/10/2x breakout with optional VIX minimum threshold.
    vix_min=None means no filter (baseline).
    vix_min=15 means only enter when VIX >= 15.
    """
    data = get_universe(tickers, start, end)
    if not data:
        print("No data"); return {}

    # VIX
    vix_series = get_vix(start, end) if vix_min is not None else None

    closes = pd.DataFrame({t: data[t]["close"] for t in data}).dropna(how="all").ffill()
    opens  = pd.DataFrame({t: data[t]["open"]  for t in data}).dropna(how="all").ffill()

    equity    = STARTING_CAPITAL
    positions = {}
    trades    = []
    equity_curve = []

    for i in range(1, len(closes)):
        today      = closes.index[i]
        prev_close = closes.iloc[i-1]
        today_open = opens.iloc[i]

        # ── Exits ─────────────────────────────────────────────────────────────
        for ticker in list(positions.keys()):
            pos   = positions[ticker]
            price = today_open.get(ticker, np.nan)
            if np.isnan(price): continue

            low_n_val = closes[ticker].iloc[max(0,i-1-EXIT_N):i-1].min()
            stop      = pos["stop"]
            exit_sig  = prev_close[ticker] < low_n_val or prev_close[ticker] <= stop
            reason    = ("10d low" if prev_close[ticker] < low_n_val else "ATR stop") if exit_sig else ""

            if exit_sig:
                slip = SLIPPAGE_CRYPTO if ticker in _CRYPTO_TICKERS else SLIPPAGE_EQUITY
                fill = price * (1 - slip)
                pnl  = (fill - pos["entry_price"]) * pos["shares"] - COMMISSION
                equity += pos["cost"] + pnl
                trades.append({
                    "ticker":      ticker,
                    "entry_date":  pos["entry_date"],
                    "exit_date":   today,
                    "entry_price": pos["entry_price"],
                    "exit_price":  fill,
                    "pnl":         round(pnl, 2),
                    "pnl_pct":     round((fill/pos["entry_price"]-1)*100, 2),
                    "exit_reason": reason,
                    "hold_days":   (today - pos["entry_date"]).days,
                    "vix_at_entry": pos.get("vix_at_entry"),
                })
                del positions[ticker]

        # ── VIX check ─────────────────────────────────────────────────────────
        vix_today = None
        if vix_series is not None:
            try:
                idx = vix_series.index.get_indexer([today], method="ffill")[0]
                vix_today = float(vix_series.iloc[idx]) if idx >= 0 else None
            except Exception:
                pass

        vix_ok = (vix_min is None) or (vix_today is not None and vix_today >= vix_min)

        # ── Entries ───────────────────────────────────────────────────────────
        for ticker in closes.columns:
            if ticker in positions or len(positions) >= len(closes.columns):
                continue
            if i < ENTRY_N + 2: continue

            price = today_open.get(ticker, np.nan)
            if np.isnan(price) or price <= 0: continue

            high_n_val = closes[ticker].iloc[max(0,i-1-ENTRY_N):i-1].max()
            entry_sig  = prev_close[ticker] > high_n_val

            if entry_sig and vix_ok:
                atr_val   = _atr(closes[ticker], i, 20)
                if atr_val <= 0: continue
                stop      = price - ATR_MULT * atr_val
                risk_unit = price - stop
                if risk_unit <= 0: continue

                slip    = SLIPPAGE_CRYPTO if ticker in _CRYPTO_TICKERS else SLIPPAGE_EQUITY
                fill    = price * (1 + slip)
                shares  = (equity * RISK_PCT) / risk_unit
                shares  = min(shares, (equity * MAX_POS_PCT) / fill)
                cost    = fill * shares + COMMISSION
                if cost > equity * 0.95 or shares <= 0: continue

                equity -= cost
                positions[ticker] = {
                    "shares":      shares,
                    "entry_price": fill,
                    "entry_date":  today,
                    "stop":        stop,
                    "cost":        cost,
                    "vix_at_entry": vix_today,
                }

        # ── Mark-to-market ────────────────────────────────────────────────────
        open_val = 0.0
        for t, pos in positions.items():
            if t in closes.columns:
                px = closes.iloc[i][t]
                px = px if px == px else pos["entry_price"]
                open_val += px * pos["shares"]
        equity_curve.append({"date": today, "equity": max(equity + open_val, 0.01)})

    # Close remaining
    for ticker, pos in positions.items():
        price = closes.iloc[-1].get(ticker, pos["entry_price"])
        if price != price: price = pos["entry_price"]
        slip  = SLIPPAGE_CRYPTO if ticker in _CRYPTO_TICKERS else SLIPPAGE_EQUITY
        fill  = price * (1 - slip)
        pnl   = (fill - pos["entry_price"]) * pos["shares"] - COMMISSION
        equity += pos.get("cost", fill * pos["shares"]) + pnl
        trades.append({
            "ticker": ticker, "entry_date": pos["entry_date"],
            "exit_date": closes.index[-1], "entry_price": pos["entry_price"],
            "exit_price": fill, "pnl": round(pnl, 2),
            "pnl_pct": round((fill/pos["entry_price"]-1)*100, 2),
            "exit_reason": "end_of_test", "hold_days": (closes.index[-1]-pos["entry_date"]).days,
            "vix_at_entry": pos.get("vix_at_entry"),
        })
    equity_curve.append({"date": closes.index[-1], "equity": equity})

    # ── Stats ─────────────────────────────────────────────────────────────────
    df_eq = pd.DataFrame(equity_curve).set_index("date")["equity"].dropna()
    df_tr = pd.DataFrame(trades) if trades else pd.DataFrame()
    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    final = df_eq.iloc[-1] if len(df_eq) else STARTING_CAPITAL
    cagr  = (final/STARTING_CAPITAL)**(1/years) - 1 if years > 0 and final > 0 else 0

    roll_max = df_eq.cummax()
    max_dd   = ((df_eq - roll_max)/roll_max).min()
    daily_r  = df_eq.pct_change().dropna()
    sharpe   = daily_r.mean()/daily_r.std()*np.sqrt(252) if daily_r.std() > 0 else 0

    n  = len(df_tr)
    nw = (df_tr["pnl"] > 0).sum() if n else 0
    gp = df_tr[df_tr["pnl"]>0]["pnl"].sum() if n else 0
    gl = abs(df_tr[df_tr["pnl"]<=0]["pnl"].sum()) or 1
    pf = gp/gl

    by_ticker = {}
    if n:
        for tkr, grp in df_tr.groupby("ticker"):
            wins = (grp["pnl"] > 0).sum()
            by_ticker[tkr] = {
                "trades": len(grp),
                "pnl": round(grp["pnl"].sum(), 2),
                "win_rate": round(wins/len(grp)*100, 1),
            }

    return {
        "label": label, "vix_min": vix_min,
        "cagr_pct": round(cagr*100, 2),
        "sharpe": round(sharpe, 3),
        "max_dd_pct": round(max_dd*100, 2),
        "profit_factor": round(pf, 3),
        "n_trades": n,
        "win_rate": round(nw/n*100, 1) if n else 0,
        "avg_trade": round(df_tr["pnl"].mean(), 2) if n else 0,
        "avg_hold": round(df_tr["hold_days"].mean(), 1) if n else 0,
        "final_equity": round(final, 2),
        "trades_per_year": round(n/years, 1) if years > 0 else 0,
        "by_ticker": by_ticker,
        "trades_df": df_tr,
    }


# ── Run tests ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'='*100}")
    print(f"  VIX REGIME FILTER TEST — 20/10/2x breakout on {', '.join(UNIVERSE)}")
    print(f"{'='*100}")

    thresholds = [None, 12, 15, 18, 20]
    results_in  = []
    results_oos = []

    for vix_min in thresholds:
        label = f"VIX≥{vix_min}" if vix_min else "No filter"
        print(f"\n  Running {label}...")
        r_in  = run_vix_backtest(UNIVERSE, IN_S,  IN_E,  vix_min, label=label)
        r_oos = run_vix_backtest(UNIVERSE, OOS_S, OOS_E, vix_min, label=label)
        results_in.append(r_in)
        results_oos.append(r_oos)

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n\n{'='*100}")
    print(f"  IN-SAMPLE (2018–2021)")
    print(f"{'='*100}")
    headers = ["VIX Filter","CAGR","Sharpe","MaxDD","PF","Trades","Tr/yr","WR%","AvgTrade","Final $"]
    rows_in = []
    for r in results_in:
        rows_in.append([
            f"≥{r['vix_min']}" if r['vix_min'] else "None",
            f"{r['cagr_pct']:+.1f}%", f"{r['sharpe']:.3f}",
            f"{r['max_dd_pct']:.1f}%", f"{r['profit_factor']:.2f}",
            r['n_trades'], r['trades_per_year'],
            f"{r['win_rate']:.1f}%", f"${r['avg_trade']:.2f}",
            f"${r['final_equity']:,.0f}",
        ])
    print(tabulate(rows_in, headers=headers, tablefmt="simple"))

    print(f"\n{'='*100}")
    print(f"  OUT-OF-SAMPLE (2022–2025)")
    print(f"{'='*100}")
    rows_oos = []
    for r in results_oos:
        flag = " ★" if r['sharpe'] >= 0.8 and r['n_trades'] >= 20 else ""
        rows_oos.append([
            f"≥{r['vix_min']}" if r['vix_min'] else "None",
            f"{r['cagr_pct']:+.1f}%", f"{r['sharpe']:.3f}",
            f"{r['max_dd_pct']:.1f}%", f"{r['profit_factor']:.2f}",
            r['n_trades'], r['trades_per_year'],
            f"{r['win_rate']:.1f}%", f"${r['avg_trade']:.2f}",
            f"${r['final_equity']:,.0f}" + flag,
        ])
    print(tabulate(rows_oos, headers=headers, tablefmt="simple"))

    # ── Ticker breakdown for best OOS result ──────────────────────────────────
    best_oos = max(results_oos, key=lambda r: r["sharpe"] if r["n_trades"] >= 15 else 0)
    print(f"\n  Best OOS result: VIX≥{best_oos['vix_min'] or 'None'} | "
          f"Sharpe={best_oos['sharpe']:.3f} | {best_oos['n_trades']} trades")
    print(f"\n  P&L by ticker ({best_oos['label']}, OOS):")
    for tkr, s in sorted(best_oos["by_ticker"].items(), key=lambda x: -x[1]["pnl"]):
        print(f"    {tkr:8s}  ${s['pnl']:>+8.0f}  {s['trades']:3d}tr  win%={s['win_rate']:.0f}")

    # ── Walk-forward by year for best result ──────────────────────────────────
    best_vix = best_oos["vix_min"]
    print(f"\n  Walk-forward by year (VIX≥{best_vix or 'None'}):")
    print(f"  {'Year':6s}  {'CAGR':>8s}  {'Sharpe':>7s}  {'Trades':>7s}  {'P&L':>8s}")
    print(f"  {'-'*6}  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*8}")
    for yr in range(2019, 2026):
        try:
            r = run_vix_backtest(UNIVERSE, f"{yr}-01-01", f"{yr}-12-31",
                                 best_vix, label=str(yr))
            pnl = r["final_equity"] - STARTING_CAPITAL
            flag = " ★" if r["sharpe"] > 0.8 else (" ✗" if pnl < 0 else "")
            print(f"  {yr:6d}  {r['cagr_pct']:>7.1f}%  {r['sharpe']:>7.3f}  "
                  f"{r['n_trades']:>7d}  ${pnl:>+8.0f}{flag}")
        except Exception as e:
            print(f"  {yr:6d}  ERROR: {e}")

    print(f"\n  Baseline (55/10 crypto-only, no VIX filter) for comparison:")
    print(f"  OOS: CAGR=+18.5%  Sharpe=1.267  MaxDD=-6.9%  Trades=43 (12/yr)")
