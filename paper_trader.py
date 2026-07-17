"""
paper_trader.py — Daily paper trading engine
Crypto Breakout Trend: BTC/ETH/SOL, 55/10/2.0x, 0.25% risk

Run once daily after market close (8pm UTC recommended).
Signal at close → fill at next open (next morning run).

Deploy: Railway cron job, or local cron: 0 20 * * * python3 paper_trader.py

State:  paper_state.json  (positions, equity, history)
Log:    paper_log.csv     (every decision, every day)
"""

import json
import csv
import os
import time
import requests
import numpy as np
from datetime import datetime, timezone, date
from pathlib import Path

# ── Config (freeze these — do not tune) ──────────────────────────────────────
ENTRY_DAYS    = 55
EXIT_DAYS     = 10
ATR_PERIOD    = 20
ATR_MULT      = 2.0
RISK_PCT      = 0.0025        # 0.25% of equity per trade
MAX_POSITIONS = 1             # start conservative
SLIPPAGE      = 0.001         # 0.1% assumed
COMMISSION    = 1.0           # $1 per trade
STARTING_CAP  = 10_000.0     # paper starting capital

TICKERS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TICKER_DISPLAY = {"BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD", "SOLUSDT": "SOL-USD"}

# ── Telegram ──────────────────────────────────────────────────────────────────
TG_TOKEN  = os.getenv("TELEGRAM_TOKEN", "")
TG_CHAT   = os.getenv("TELEGRAM_CHAT_ID", "")

def notify(msg: str):
    if not TG_TOKEN or not TG_CHAT:
        print(f"[notify] {msg}")
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TG_CHAT, "text": msg}, timeout=10)
    except Exception as e:
        print(f"[notify error] {e}")

# ── State persistence ─────────────────────────────────────────────────────────
STATE_FILE = Path("paper_state.json")
LOG_FILE   = Path("paper_log.csv")

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "equity":    STARTING_CAP,
        "positions": {},   # ticker → {shares, entry_price, stop, entry_date, cost}
        "trade_history": [],
        "last_run": None,
    }

def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))

def log_decision(row: dict):
    write_header = not LOG_FILE.exists()
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=row.keys())
        if write_header:
            w.writeheader()
        w.writerow(row)

# ── Data ──────────────────────────────────────────────────────────────────────
def fetch_closes(symbol: str, limit: int = 80) -> list[dict]:
    """Fetch daily OHLCV from Binance (no API key needed)."""
    url = "https://api.binance.us/api/v3/klines"
    params = {"symbol": symbol, "interval": "1d", "limit": limit}
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if isinstance(data, dict) and data.get("code"):
                raise ValueError(f"Binance error: {data}")
            return [
                {
                    "date":   datetime.fromtimestamp(int(row[0])/1000, tz=timezone.utc).date(),
                    "open":   float(row[1]),
                    "high":   float(row[2]),
                    "low":    float(row[3]),
                    "close":  float(row[4]),
                    "volume": float(row[5]),
                }
                for row in data
            ]
        except Exception as e:
            print(f"[fetch] {symbol} attempt {attempt+1} failed: {e}")
            time.sleep(2)
    return []

# ── Indicators ────────────────────────────────────────────────────────────────
def atr(bars: list[dict], period: int) -> float:
    if len(bars) < period + 1:
        return 0.0
    trs = [abs(bars[i]["close"] - bars[i-1]["close"]) for i in range(-period, 0)]
    return np.mean(trs)

def high_n(bars: list[dict], n: int) -> float:
    """Highest close over last n bars EXCLUDING today."""
    closes = [b["close"] for b in bars[-(n+1):-1]]
    return max(closes) if closes else 0.0

def low_n(bars: list[dict], n: int) -> float:
    """Lowest close over last n bars EXCLUDING today."""
    closes = [b["close"] for b in bars[-(n+1):-1]]
    return min(closes) if closes else float("inf")

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    today     = date.today()
    now_utc   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    state     = load_state()
    equity    = state["equity"]
    positions = state["positions"]   # mutable
    signals   = []

    print(f"\n{'='*60}")
    print(f"  Crypto Breakout Trend — {now_utc}")
    print(f"  Equity: ${equity:,.2f}  |  Positions: {len(positions)}")
    print(f"{'='*60}")

    for symbol in TICKERS:
        display = TICKER_DISPLAY[symbol]
        bars = fetch_closes(symbol, limit=ENTRY_DAYS + 5)

        if len(bars) < ENTRY_DAYS + 2:
            print(f"  {display}: insufficient data ({len(bars)} bars)")
            continue

        # Use yesterday's close for signal (today not complete)
        today_open  = bars[-1]["open"]    # today's open = fill price
        yesterday   = bars[-2]
        prev_close  = yesterday["close"]
        atr_val     = atr(bars[:-1], ATR_PERIOD)
        entry_high  = high_n(bars[:-1], ENTRY_DAYS)
        exit_low    = low_n(bars[:-1], EXIT_DAYS)

        in_position = symbol in positions
        pos         = positions.get(symbol, {})

        # ── EXIT CHECK ────────────────────────────────────────────────────────
        if in_position:
            fill   = today_open * (1 - SLIPPAGE)
            stop   = pos["stop"]
            pnl    = None
            reason = None

            if prev_close < exit_low:
                reason = f"10d low break (close {prev_close:.4f} < low {exit_low:.4f})"
            elif prev_close <= stop:
                reason = f"ATR stop hit (close {prev_close:.4f} <= stop {stop:.4f})"

            if reason:
                pnl = (fill - pos["entry_price"]) * pos["shares"] - COMMISSION
                equity += pos["cost"] + pnl
                trade = {
                    "type":        "CLOSE",
                    "ticker":      display,
                    "entry_date":  pos["entry_date"],
                    "exit_date":   str(today),
                    "entry_price": pos["entry_price"],
                    "exit_price":  round(fill, 4),
                    "shares":      pos["shares"],
                    "pnl":         round(pnl, 2),
                    "reason":      reason,
                    "equity":      round(equity, 2),
                }
                state["trade_history"].append(trade)
                del positions[symbol]
                signals.append(f"🔴 CLOSE {display} @ ${fill:,.2f} | P&L ${pnl:+.2f} | {reason}")
                print(f"  {display}: EXIT — {reason} | P&L ${pnl:+.2f}")
                log_decision({
                    "date": today, "ticker": display, "action": "CLOSE",
                    "close": prev_close, "fill": round(fill,4),
                    "pnl": round(pnl,2), "equity": round(equity,2),
                    "reason": reason,
                    "entry_days": ENTRY_DAYS, "exit_days": EXIT_DAYS, "atr_mult": ATR_MULT,
                })
                continue

            # Update stop (trail if possible — no trailing in basic version)
            unrealised = (prev_close - pos["entry_price"]) * pos["shares"]
            print(f"  {display}: HOLD @ ${prev_close:,.4f} | "
                  f"entry ${pos['entry_price']:.4f} | stop ${stop:.4f} | "
                  f"unreal ${unrealised:+.2f}")
            log_decision({
                "date": today, "ticker": display, "action": "HOLD",
                "close": prev_close, "fill": None, "pnl": None,
                "equity": round(equity + unrealised, 2),
                "reason": f"unrealised ${unrealised:+.2f}",
                "entry_days": ENTRY_DAYS, "exit_days": EXIT_DAYS, "atr_mult": ATR_MULT,
            })
            continue

        # ── ENTRY CHECK ───────────────────────────────────────────────────────
        entry_signal = prev_close > entry_high
        print(f"  {display}: close={prev_close:.4f} | "
              f"55d-high={entry_high:.4f} | signal={'✓' if entry_signal else '✗'} | "
              f"atr={atr_val:.4f}")

        if entry_signal and len(positions) < MAX_POSITIONS and atr_val > 0:
            fill      = today_open * (1 + SLIPPAGE)
            stop      = fill - ATR_MULT * atr_val
            risk_unit = fill - stop
            if risk_unit <= 0:
                print(f"  {display}: bad risk unit {risk_unit:.4f} — skip")
                continue

            shares    = (equity * RISK_PCT) / risk_unit
            cost      = fill * shares + COMMISSION
            max_cost  = equity * 0.90
            if cost > max_cost:
                shares = (max_cost - COMMISSION) / fill
                cost   = fill * shares + COMMISSION

            if shares <= 0 or cost > equity:
                print(f"  {display}: insufficient equity — skip")
                continue

            equity -= cost
            positions[symbol] = {
                "shares":      round(shares, 6),
                "entry_price": round(fill, 6),
                "stop":        round(stop, 6),
                "entry_date":  str(today),
                "cost":        round(cost, 4),
                "atr_at_entry": round(atr_val, 6),
            }
            signals.append(
                f"🟢 ENTER {display} @ ${fill:,.4f} | "
                f"shares={shares:.4f} | stop=${stop:.4f} | "
                f"risk=${equity*RISK_PCT:.2f}"
            )
            print(f"  {display}: ENTRY @ ${fill:.4f} | shares={shares:.4f} | "
                  f"stop=${stop:.4f} | cost=${cost:.2f}")
            log_decision({
                "date": today, "ticker": display, "action": "ENTER",
                "close": prev_close, "fill": round(fill,4), "pnl": None,
                "equity": round(equity, 2),
                "reason": f"55d breakout close {prev_close:.4f} > high {entry_high:.4f}",
                "entry_days": ENTRY_DAYS, "exit_days": EXIT_DAYS, "atr_mult": ATR_MULT,
            })
        else:
            log_decision({
                "date": today, "ticker": display, "action": "NO_SIGNAL",
                "close": prev_close, "fill": None, "pnl": None,
                "equity": round(equity, 2),
                "reason": (f"no breakout (close {prev_close:.4f} <= high {entry_high:.4f})"
                           if not entry_signal else
                           f"max positions ({len(positions)}/{MAX_POSITIONS})"),
                "entry_days": ENTRY_DAYS, "exit_days": EXIT_DAYS, "atr_mult": ATR_MULT,
            })

    # ── Save and notify ───────────────────────────────────────────────────────
    open_unreal = sum(
        (fetch_closes(sym, 5)[-1]["close"] - pos["entry_price"]) * pos["shares"]
        for sym, pos in positions.items()
        if pos
    ) if positions else 0.0

    state["equity"]    = round(equity, 4)
    state["positions"] = positions
    state["last_run"]  = str(today)
    save_state(state)

    total_trades = len(state["trade_history"])
    wins  = sum(1 for t in state["trade_history"] if t.get("pnl", 0) > 0)
    wr    = wins / total_trades * 100 if total_trades else 0
    total_pnl = sum(t.get("pnl", 0) for t in state["trade_history"])

    summary = (
        f"📊 LeapFrog Paper | {today}\n"
        f"Equity: ${equity:,.2f} (cash) | Unreal: ${open_unreal:+.2f}\n"
        f"Total: {total_trades} trades | WR: {wr:.0f}% | P&L: ${total_pnl:+.2f}\n"
        f"Positions: {len(positions)}/{MAX_POSITIONS}"
    )

    if signals:
        summary += "\n\nSignals today:\n" + "\n".join(signals)
    else:
        summary += "\n\nNo signals today — hunting."

    print(f"\n{summary}")
    notify(summary)

    print(f"\n  State saved → {STATE_FILE}")
    print(f"  Log appended → {LOG_FILE}\n")


if __name__ == "__main__":
    run()
