"""slots_replay.py - 2/3/4 slots using the REAL paper-trader code (replay), mark-to-market curve.
Replaces slots_test.py, which used nvda_check's engine (trades equities on weekends, short windows).
DECISION RULE (frozen, unchanged): adopt 4 slots only if OOS Sharpe >= 2-slot AND OOS max DD no worse.
Uses temp files only; never touches your state or logs.
Usage: python3 slots_replay.py [module=paper_trader]"""
import sys, io, json, bisect, tempfile, contextlib, importlib
from datetime import date as real_date
from pathlib import Path
import numpy as np, pandas as pd

MODULE = sys.argv[1] if len(sys.argv) > 1 else "paper_trader"
START, END = "2018-01-01", "2025-06-01"
IS_END, OOS_START = pd.Timestamp("2021-12-31"), pd.Timestamp("2022-01-01")
import os
SLOTS, WARMUP = [int(x) for x in os.environ.get('SLOTS', '2,3,4').split(',')], 26

src = Path("nvda_check.py").read_text()
marker = "IS_START,  IS_END"
assert marker in src, "marker not found in nvda_check.py"
ns = {"__name__": "nvda_defs"}
exec(compile(src.split(marker)[0], "nvda_defs", "exec"), ns)
get_bars = ns["get_bars"]

pt = importlib.import_module(MODULE)
assert hasattr(pt, "run") and hasattr(pt, "TICKERS") and hasattr(pt, "fetch_bars"), "unexpected module shape"
START_CAP = getattr(pt, "STARTING_CAP", 10_000.0)

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
print(f"Module: {MODULE} | {union[0]} -> {union[-1]} | {len(union)} days | {[v['display'] for v in pt.TICKERS.values()]}")

cur = {"D": None}
def fake_fetch_bars(symbol, info, limit=40):
    ds = dates[symbol]; k = bisect.bisect_right(ds, cur["D"])
    if k == 0 or ds[k - 1] != cur["D"]:
        return []
    return bars[symbol][max(0, k - limit):k]

class FakeDate(real_date):
    _d = None
    @classmethod
    def today(cls): return cls._d

pt.fetch_bars, pt.notify, pt.date = fake_fetch_bars, (lambda m: None), FakeDate
import os
if os.environ.get('SLIP'):
    assert hasattr(pt, 'SLIPPAGE'), 'module has no SLIPPAGE constant'
    pt.SLIPPAGE = float(os.environ['SLIP'])
    print(f'Slippage per side set to {pt.SLIPPAGE:.2%}')

def simulate(k):
    pt.MAX_POSITIONS = k
    tmp = Path(tempfile.mkdtemp())
    pt.STATE_FILE, pt.LOG_FILE = tmp / "state.json", tmp / "log.csv"
    vals, idx = [], []
    for D in union[WARMUP:]:
        cur["D"], FakeDate._d = D, D
        with contextlib.redirect_stdout(io.StringIO()):
            pt.run()
        st = json.loads(pt.STATE_FILE.read_text())
        mv = 0.0
        for sym, p in st["positions"].items():
            kk = bisect.bisect_right(dates[sym], D)
            px = bars[sym][kk - 1]["close"] if kk else p["entry_price"]
            mv += px * p["shares"]
        vals.append(st["equity"] + mv); idx.append(pd.Timestamp(D))
    tr = pd.DataFrame(st["trade_history"])
    if len(tr):
        tr["exit_ts"] = pd.to_datetime(tr["exit_date"])
    return pd.Series(vals, index=idx), tr

def seg(curve, tr, lo, hi):
    c = curve[(curve.index >= lo) & (curve.index <= hi)]
    r = c.pct_change().dropna()
    sharpe = float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0
    dd = float((c / c.cummax() - 1).min())
    yrs = max((c.index[-1] - c.index[0]).days / 365.25, 1e-9)
    cagr = (c.iloc[-1] / c.iloc[0]) ** (1 / yrs) - 1
    t = tr[(tr["exit_ts"] >= lo) & (tr["exit_ts"] <= hi)] if len(tr) else tr
    n = len(t); w = int((t["pnl"] > 0).sum()) if n else 0
    gw = float(t.loc[t["pnl"] > 0, "pnl"].sum()) if n else 0.0
    gl = float(-t.loc[t["pnl"] <= 0, "pnl"].sum()) if n else 0.0
    return {"sharpe": sharpe, "dd": dd, "cagr": cagr, "n": n, "wr": (w / n * 100) if n else 0.0,
            "pf": (gw / gl) if gl > 0 else (float("inf") if gw > 0 else 0.0), "pnl": gw - gl}

def line(s):
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    return (f"CAGR={s['cagr']:+.1%} Sharpe={s['sharpe']:.2f} DD={s['dd']:.1%} PF={pf} "
            f"Trades={s['n']} WR={s['wr']:.0f}% P&L=${s['pnl']:+,.0f}")

res = {}
yrs_full = (union[-1] - union[WARMUP]).days / 365.25
print(f"\n{'=' * 78}\n  REAL-CODE REPLAY: slot comparison\n{'=' * 78}")
for k in SLOTS:
    curve, tr = simulate(k)
    i_s = seg(curve, tr, curve.index[0], IS_END)
    o_s = seg(curve, tr, OOS_START, curve.index[-1])
    res[k] = o_s
    n_all = len(tr)
    print(f"  {k} slots  IS : {line(i_s)}\n  {k} slots  OOS: {line(o_s)}")
    print(f"           all trades: {n_all} = {n_all / yrs_full:.1f}/yr -> {30 / (n_all / yrs_full):.1f} yrs to 30" if n_all else "           no trades")
a, b = res[2], res[4]
ok = b["sharpe"] >= a["sharpe"] and b["dd"] >= a["dd"]
print(f"\n  RULE: 4-slot OOS Sharpe {b['sharpe']:.2f} vs {a['sharpe']:.2f}, DD {b['dd']:.1%} vs {a['dd']:.1%}"
      f"  ->  {'ADOPT 4 SLOTS' if ok else 'KEEP 2 SLOTS'}\n")
