"""replay.py - does the LIVE paper-trader code reproduce the backtest engine's trades?
Runs the real trader module's run() once per historical day (fetch_bars, today's date and
state files are swapped out; trading logic untouched), then compares to nvda_check.run_backtest
on identical data. Read-only: uses temp files, never touches your state or logs.
Usage: python3 replay.py [module=paper_trader] [start=2021-06-01] [end=2025-06-01]"""
import sys, io, json, bisect, tempfile, contextlib, importlib
from datetime import date as real_date
from pathlib import Path
import pandas as pd

MODULE = sys.argv[1] if len(sys.argv) > 1 else "paper_trader"
START = sys.argv[2] if len(sys.argv) > 2 else "2021-06-01"
END = sys.argv[3] if len(sys.argv) > 3 else "2025-06-01"
WARMUP = 26   # same first-trading-index as nvda_check (max(ENTRY_DAYS+1, ATR_PERIOD+1))

src = Path("nvda_check.py").read_text()
marker = "IS_START,  IS_END"
assert marker in src, "marker not found in nvda_check.py"
ns = {"__name__": "nvda_defs"}
exec(compile(src.split(marker)[0], "nvda_defs", "exec"), ns)
get_bars, run_backtest = ns["get_bars"], ns["run_backtest"]

pt = importlib.import_module(MODULE)
assert hasattr(pt, "run") and hasattr(pt, "TICKERS") and hasattr(pt, "fetch_bars"), "unexpected module shape"
displays = [v["display"] for v in pt.TICKERS.values()]

bars, dates = {}, {}
with contextlib.redirect_stdout(io.StringIO()):
    for sym, info in pt.TICKERS.items():
        df = get_bars(info["display"], START, END)
        idx = pd.to_datetime(df.index)
        if idx.tz is not None:
            idx = idx.tz_convert(None)
        df = df.copy(); df.index = idx
        bars[sym] = [{"date": ts.date(), "open": float(r["open"]), "high": float(r["high"]),
                      "low": float(r["low"]), "close": float(r["close"]), "volume": float(r.get("volume", 0))}
                     for ts, r in df.iterrows()]
        dates[sym] = [b["date"] for b in bars[sym]]
union = sorted(set().union(*[set(d) for d in dates.values()]))
print(f"Module: {MODULE} | slots: {pt.MAX_POSITIONS} | {union[0]} -> {union[-1]} | {len(union)} days | {displays}")

cur = {"D": None}
def fake_fetch_bars(symbol, info, limit=40):
    ds = dates[symbol]; k = bisect.bisect_right(ds, cur["D"])
    if k == 0 or ds[k - 1] != cur["D"]:
        return []              # no bar today for this symbol (equity weekend/holiday): skipped, as in the backtest
    return bars[symbol][max(0, k - limit):k]

class FakeDate(real_date):
    _d = None
    @classmethod
    def today(cls): return cls._d

tmp = Path(tempfile.mkdtemp())
pt.STATE_FILE, pt.LOG_FILE = tmp / "state.json", tmp / "log.csv"
pt.fetch_bars, pt.notify, pt.date = fake_fetch_bars, (lambda m: None), FakeDate

for D in union[WARMUP:]:
    cur["D"], FakeDate._d = D, D
    with contextlib.redirect_stdout(io.StringIO()):
        pt.run()

live = pd.DataFrame(json.loads(pt.STATE_FILE.read_text())["trade_history"])
with contextlib.redirect_stdout(io.StringIO()):
    bt = run_backtest(displays, START, END, pt.MAX_POSITIONS)
btd = pd.DataFrame(bt["trade_list"])
live["key"] = live["ticker"] + "|" + live["exit_date"].astype(str)
btd["key"] = btd["ticker"] + "|" + btd["date"].astype(str).str[:10]
m = live.merge(btd, on="key", how="outer", suffixes=("_live", "_bt"), indicator=True)
both = m[m["_merge"] == "both"].copy()
close = lambda a, b: ((a - b).abs() / b.abs().clip(lower=1e-9)) < 1e-5
both["px_ok"] = close(both["entry_price"], both["entry"]) & close(both["exit_price"], both["exit"])
lo, bo = m[m["_merge"] == "left_only"], m[m["_merge"] == "right_only"]

print(f"\n  live trades: {len(live)}   backtest trades: {len(btd)}")
print(f"  same ticker+exit day: {len(both)}   of which same entry+exit prices: {int(both['px_ok'].sum())}")
print(f"  live-only: {len(lo)}   backtest-only: {len(bo)}")
print(f"  total P&L  live ${live['pnl'].sum():+,.0f}   backtest ${btd['pnl'].sum():+,.0f}")
if len(lo) or len(bo) or not both["px_ok"].all():
    print("\n  FIRST DIVERGENCES (by exit date):")
    bad = pd.concat([lo.assign(why="live only"), bo.assign(why="backtest only"),
                     both[~both["px_ok"]].assign(why="price differs")]).sort_values("key")
    for _, r in bad.head(12).iterrows():
        print(f"    {r['key']:26} {r['why']:14} pnl_live={r.get('pnl_live')} pnl_bt={r.get('pnl_bt')}")
    print("\n  Per-ticker trade counts (live / backtest):")
    for t in displays:
        print(f"    {t:8} {int((live['ticker'] == t).sum()):4} / {int((btd['ticker'] == t).sum()):4}")
    print("\n  RESULT: LIVE CODE DOES NOT REPRODUCE THE BACKTEST")
else:
    print("\n  RESULT: LIVE CODE REPRODUCES THE BACKTEST (trade-for-trade)")
print()
