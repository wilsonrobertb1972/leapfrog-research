#!/usr/bin/env python3
"""report.py - READ-ONLY dashboard for both paper traders. Safe to run any time."""
import csv, json
from datetime import date
from pathlib import Path

START, GATE = 10_000.0, 30
SYSTEMS = [("2-slot", "paper_state.json", "paper_log.csv"),
           ("4-slot", "paper_state_4slot.json", "paper_log_4slot.csv")]
DISPLAY = {"BTCUSDT": "BTC-USD", "SOLUSDT": "SOL-USD", "NVDA": "NVDA", "GLD": "GLD"}


def last_closes(log: Path) -> dict:
    out = {}
    if log.exists():
        with open(log, newline="") as f:
            for r in csv.DictReader(f):
                try:
                    out[r["ticker"]] = (float(r["close"]), r["date"])
                except (KeyError, ValueError, TypeError):
                    pass
    return out


def count_data_fails(log: Path) -> int:
    if not log.exists():
        return 0
    with open(log, newline="") as f:
        return sum(1 for r in csv.DictReader(f) if r.get("action") == "DATA_FAIL")


def stats(trades: list) -> dict:
    pnls = [float(t.get("pnl") or 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gl = -sum(losses)
    pf = (sum(wins) / gl) if gl > 0 else (float("inf") if wins else 0.0)
    eq = peak = START
    dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"n": len(pnls), "wins": len(wins), "total": sum(pnls), "pf": pf, "dd": dd,
            "wr": (len(wins) / len(pnls) * 100) if pnls else 0.0,
            "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
            "avg_loss": (sum(losses) / len(losses)) if losses else 0.0}


def report(name, state_f, log_f):
    sp, lp = Path(state_f), Path(log_f)
    print(f"\n{'=' * 64}\n  {name.upper()}   ({state_f})\n{'=' * 64}")
    if not sp.exists():
        print("  state file not found"); return None
    st = json.loads(sp.read_text())
    cash, positions, trades = st["equity"], st.get("positions", {}), st.get("trade_history", [])
    closes, mv_total, rows = last_closes(lp), 0.0, []
    for sym, p in positions.items():
        px, pxd = closes.get(DISPLAY.get(sym, sym), (p["entry_price"], "n/a"))
        mv = px * p["shares"]
        mv_total += mv
        rows.append((DISPLAY.get(sym, sym), p["entry_date"], p["entry_price"], px, pxd, p["stop"],
                     (px - p["entry_price"]) * p["shares"], (px / p["stop"] - 1) * 100))
    total = cash + mv_total
    s = stats(trades)

    stale = st.get("last_run") != str(date.today())
    print(f"  Last run: {st.get('last_run')}" + ("   <-- NOT RUN TODAY" if stale else ""))
    print(f"  Total equity (cash + open positions, approx): ${total:,.2f}  "
          f"({(total / START - 1) * 100:+.2f}% vs ${START:,.0f})")
    print(f"  Cash: ${cash:,.2f}   Open positions value: ${mv_total:,.2f}")

    print("\n  OPEN POSITIONS")
    if rows:
        print(f"  {'tkr':8}{'since':12}{'entry':>10}{'last':>10}{'stop':>10}{'unreal $':>11}{'to stop':>9}")
        for t, d, e, px, pxd, stp, u, ds in rows:
            print(f"  {t:8}{d:12}{e:>10,.2f}{px:>10,.2f}{stp:>10,.2f}{u:>+11.2f}{ds:>8.1f}%")
    else:
        print("  none")

    print(f"\n  CLOSED TRADES: {s['n']}   (gate: {GATE}, {s['n'] / GATE * 100:.0f}% there)")
    if s["n"]:
        pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
        print(f"  Win rate {s['wr']:.0f}% ({s['wins']}W/{s['n'] - s['wins']}L) | realised ${s['total']:+,.2f}")
        print(f"  Avg win ${s['avg_win']:+.2f} | avg loss ${s['avg_loss']:+.2f} | profit factor {pf} | max DD ${s['dd']:,.2f}")
        print("  Last 5:")
        for t in trades[-5:]:
            print(f"    {t['exit_date']}  {t['ticker']:8} ${float(t['pnl']):+8.2f}  {t['reason']}")
    fails = count_data_fails(lp)
    if fails:
        print(f"\n  WARNING: {fails} DATA_FAIL rows in log - check for skipped exit checks")
    return {"name": name, "total": total, "n": s["n"], "wr": s["wr"], "pnl": s["total"], "open": len(positions)}


if __name__ == "__main__":
    res = [r for r in (report(*s) for s in SYSTEMS) if r]
    if len(res) == 2:
        a, b = res
        print(f"\n{'=' * 64}\n  COMPARISON\n{'=' * 64}")
        print(f"  {'':10}{'equity':>12}{'trades':>8}{'win%':>7}{'realised':>11}{'open':>6}")
        for r in res:
            print(f"  {r['name']:10}${r['total']:>11,.2f}{r['n']:>8}{r['wr']:>6.0f}%{r['pnl']:>+11.2f}{r['open']:>6}")
        if min(a["n"], b["n"]) < 10:
            print("\n  Note: <10 closed trades each - slot-count comparison is noise, not evidence.")
    print()
