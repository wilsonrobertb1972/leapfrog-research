"""stage_b.py - v2 expansion Stage B, exactly per UNIVERSE_EXPANSION_CRITERIA_v2.md (frozen, commit 871ad6c).
Real-code replay of paper_trader.py (temp files only). Per-asset floors first, then portfolio gates.
Usage: python3 stage_b.py [module=paper_trader] [--info]   (--info adds correlation matrix and 4-slot result)"""
import sys, io, json, bisect, tempfile, contextlib, importlib
from datetime import date as real_date
from pathlib import Path
import numpy as np, pandas as pd

MODULE = next((a for a in sys.argv[1:] if not a.startswith("--")), "paper_trader")
INFO = "--info" in sys.argv
START, END = "2018-01-01", "2025-06-01"
OOS_START = pd.Timestamp("2022-01-01")
WARMUP = 26
LIVE = ["BTC-USD", "SOL-USD", "NVDA", "GLD"]
CANDS = ["ETH-USD", "XRP-USD", "ZEC-USD", "NEAR-USD", "DOGE-USD", "ADA-USD", "LINK-USD", "UNI-USD", "LTC-USD"]  # 90d volume rank order
PRIMARY, STRESS = 0.005, 0.009
A_SHARPE, A_PF, A_TRADES = 0.5, 1.5, 8
P_SHARPE, P_DD, LOO_SHARPE, P_RATE, S_SHARPE = 1.29, -0.10, 1.12, 26.0, 0.88

src = Path("nvda_check.py").read_text()
marker = "IS_START,  IS_END"
assert marker in src, "marker not found in nvda_check.py"
ns = {"__name__": "nvda_defs"}
exec(compile(src.split(marker)[0], "nvda_defs", "exec"), ns)
get_bars = ns["get_bars"]

pt = importlib.import_module(MODULE)
assert hasattr(pt, "run") and hasattr(pt, "fetch_bars"), "unexpected module shape"

bars, dates, closes = {}, {}, {}
with contextlib.redirect_stdout(io.StringIO()):
    for t in LIVE + CANDS:
        df = get_bars(t, START, END)
        idx = pd.to_datetime(df.index)
        if idx.tz is not None:
            idx = idx.tz_convert(None)
        df = df.copy(); df.index = idx
        bars[t] = [{"date": ts.date(), "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
                    "close": float(r["close"]), "volume": float(r.get("volume", 0))} for ts, r in df.iterrows()]
        dates[t] = [b["date"] for b in bars[t]]
        closes[t] = pd.Series(df["close"].values, index=idx)

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

def simulate(tickers, slots, slip):
    pt.TICKERS = {t: {"display": t, "type": "crypto" if t.endswith("-USD") else "equity"} for t in tickers}
    pt.MAX_POSITIONS, pt.SLIPPAGE = slots, slip
    union = sorted(set().union(*[set(dates[t]) for t in tickers]))
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
            mv += (bars[sym][kk - 1]["close"] if kk else p["entry_price"]) * p["shares"]
        vals.append(st["equity"] + mv); idx.append(pd.Timestamp(D))
    tr = pd.DataFrame(st["trade_history"])
    if len(tr):
        tr["exit_ts"] = pd.to_datetime(tr["exit_date"])
    return pd.Series(vals, index=idx), tr

def oos(curve, tr):
    c = curve[curve.index >= OOS_START]
    r = c.pct_change().dropna()
    sharpe = float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0
    dd = float((c / c.cummax() - 1).min())
    yrs = max((c.index[-1] - c.index[0]).days / 365.25, 1e-9)
    t = tr[tr["exit_ts"] >= OOS_START] if len(tr) else tr
    n = len(t)
    gw = float(t.loc[t["pnl"] > 0, "pnl"].sum()) if n else 0.0
    gl = float(-t.loc[t["pnl"] <= 0, "pnl"].sum()) if n else 0.0
    return {"sharpe": sharpe, "dd": dd, "n": n, "rate": n / yrs,
            "pf": (gw / gl) if gl > 0 else (float("inf") if gw > 0 else 0.0), "pnl": gw - gl}

def fpf(x): return "inf" if x == float("inf") else f"{x:.2f}"

print(f"Module: {MODULE} | Stage B | primary cost {PRIMARY:.1%}/side, stress {STRESS:.1%}/side | OOS from {OOS_START.date()}")
print(f"\n{'=' * 92}\n  PER-ASSET (standalone, 1 slot, OOS, primary cost)\n{'=' * 92}")
print(f"  {'asset':9}{'Sharpe':>7}{'PF':>6}{'DD':>8}{'B&H DD':>9}{'trades':>7}   result")
admitted, results = [], {}
for t in CANDS:
    curve, tr = simulate([t], 1, PRIMARY)
    m = oos(curve, tr)
    c = closes[t][closes[t].index >= OOS_START]
    bh = float((c / c.cummax() - 1).min())
    fails = []
    if not m["sharpe"] > A_SHARPE: fails.append("Sharpe")
    if not m["pf"] > A_PF: fails.append("PF")
    if not m["dd"] > bh: fails.append("DD vs B&H")
    if not m["n"] >= A_TRADES: fails.append("trades<8")
    results[t] = {**m, "bh_dd": bh, "fails": fails}
    if not fails: admitted.append(t)
    print(f"  {t:9}{m['sharpe']:>7.2f}{fpf(m['pf']):>6}{m['dd']:>8.1%}{bh:>9.1%}{m['n']:>7}   "
          f"{'PASS' if not fails else 'FAIL: ' + ', '.join(fails)}")

print(f"\n  Admitted to portfolio test: {admitted if admitted else 'NONE'}")
verdict = "UNIVERSE STAYS AS IS"
if admitted:
    uni = LIVE + admitted
    print(f"\n{'=' * 92}\n  PORTFOLIO (live four + admitted, 2 slots, OOS)\n{'=' * 92}")
    curve, tr = simulate(uni, 2, PRIMARY)
    p = oos(curve, tr)
    g = {"Sharpe >= %.2f" % P_SHARPE: p["sharpe"] >= P_SHARPE,
         "DD <= 10%": p["dd"] >= P_DD,
         "trades/yr >= %.0f" % P_RATE: p["rate"] >= P_RATE}
    print(f"  Primary cost: Sharpe {p['sharpe']:.2f}  DD {p['dd']:.1%}  PF {fpf(p['pf'])}  OOS trades {p['n']} ({p['rate']:.1f}/yr)  P&L ${p['pnl']:+,.0f}")
    for k, v in g.items():
        print(f"    {k:22} {'PASS' if v else 'FAIL'}")
    if all(g.values()):
        print("\n  Leave-one-out (admitted candidates only):")
        loo_ok = True
        for t in admitted:
            cv, tv = simulate([u for u in uni if u != t], 2, PRIMARY)
            s = oos(cv, tv)["sharpe"]
            ok = s >= LOO_SHARPE; loo_ok &= ok
            print(f"    without {t:9} Sharpe {s:.2f}  {'PASS' if ok else 'FAIL'} (>= {LOO_SHARPE})")
        cs, ts = simulate(uni, 2, STRESS)
        s = oos(cs, ts)
        s_ok = s["sharpe"] >= S_SHARPE
        print(f"\n  Stress cost {STRESS:.1%}: Sharpe {s['sharpe']:.2f}  DD {s['dd']:.1%}  {'PASS' if s_ok else 'FAIL'} (>= {S_SHARPE})")
        verdict = "ALL GATES PASS: expansion admitted (paper_trader universe change = separate commit)" if (loo_ok and s_ok) else "GATE FAILED: universe stays as is"
    else:
        print("\n  Primary gates failed; leave-one-out and stress not run (already failed).")
        verdict = "GATE FAILED: universe stays as is"
    if INFO:
        print("\n  INFORMATIONAL: pairwise correlation of daily returns, OOS")
        rets = pd.DataFrame({t: closes[t].pct_change() for t in uni})
        rets = rets[rets.index >= OOS_START]
        print(rets.corr().round(2).to_string())
        c4, t4 = simulate(uni, 4, PRIMARY)
        q = oos(c4, t4)
        print(f"\n  INFORMATIONAL 4 slots: Sharpe {q['sharpe']:.2f}  DD {q['dd']:.1%}  trades {q['n']} ({q['rate']:.1f}/yr)")
print(f"\n  VERDICT: {verdict}\n")
json.dump({"per_asset": {k: {kk: (vv if not isinstance(vv, float) or np.isfinite(vv) else None) for kk, vv in v.items()} for k, v in results.items()},
           "admitted": admitted, "verdict": verdict}, open("stage_b_results.json", "w"), indent=2, default=str)
