"""
paper_trader_4slot.py — 4-slot parallel tracker (research only)
Same strategy as paper_trader.py but MAX_POSITIONS=4.
Runs alongside the main paper trader to compare slot-count impact.

State:  paper_state_4slot.json
Log:    paper_log_4slot.csv

Daily command:
  python3 paper_trader_4slot.py
"""

import json, csv, os, time, requests
import numpy as np
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

# ── Strategy config (FROZEN — same as main paper trader) ──────────────────────
ENTRY_DAYS    = 25
EXIT_DAYS     = 8
ATR_PERIOD    = 20
ATR_MULT      = 2.0
RISK_PCT      = 0.0025        # 0.25% of equity per trade
MAX_POSITIONS = 4             # ← the only difference from paper_trader.py
SLIPPAGE      = 0.001
COMMISSION    = 1.0
STARTING_CAP  = 10_000.0

# ── Universe (same as main) ───────────────────────────────────────────────────
TICKERS = {
    "BTCUSDT": {"display": "BTC-USD", "type": "crypto"},
    "SOLUSDT": {"display": "SOL-USD", "type": "crypto"},
    "NVDA":    {"display": "NVDA",    "type": "equity"},
    "GLD":     {"display": "GLD",     "type": "equity"},
}

# ── Separate state files — no conflict with main paper trader ─────────────────
STATE_FILE = Path("paper_state_4slot.json")
LOG_FILE   = Path("paper_log_4slot.csv")

# ── Telegram (same env vars — sends to same chat) ────────────────────────────
TG_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")

def notify(msg: str):
    if not TG_TOKEN or not TG_CHAT:
        print(f"[notify] {msg}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg}, timeout=10
        )
    except Exception as e:
        print(f"[notify error] {e}")

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "equity": STARTING_CAP,
        "positions": {},
        "trade_history": [],
        "last_run": None,
        "version": "v2-4slot-NVDA+GLD+BTC+SOL-25/8/2.0x",
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

def fetch_crypto(symbol: str, limit: int = 40) -> list[dict]:
    url = "https://api.binance.us/api/v3/klines"
    params = {"symbol": symbol, "interval": "1d", "limit": limit}
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if isinstance(data, dict):
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

def fetch_equity(symbol: str, limit: int = 40) -> list[dict]:
    try:
        import yfinance as yf
        end   = datetime.now(timezone.utc).date()
        start = end - timedelta(days=limit * 2)
        raw = None
        for _attempt in range(3):
            raw = yf.download(symbol, start=str(start), end=str(end),
                              progress=False, auto_adjust=True)
            if not raw.empty:
                break
            print(f"[fetch] {symbol} yfinance empty, attempt {_attempt+1}")
            time.sleep(3)
        if raw is None or raw.empty:
            return []
        if isinstance(raw.columns, __import__('pandas').MultiIndex):
            raw.columns = [c[0].lower() for c in raw.columns]
        else:
            raw.columns = [c.lower() for c in raw.columns]
        bars = []
        for ts, row in raw.iterrows():
            bars.append({
                "date":   ts.date() if hasattr(ts, "date") else ts,
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row.get("volume", 0)),
            })
        return bars[-limit:]
    except Exception as e:
        print(f"[fetch] {symbol} yfinance error: {e}")
        return []

def fetch_bars(symbol: str, ticker_info: dict, limit: int = 40) -> list[dict]:
    if ticker_info["type"] == "crypto":
        return fetch_crypto(symbol, limit)
    else:
        return fetch_equity(symbol, limit)

def calc_atr(bars: list[dict], period: int) -> float:
    if len(bars) < period + 1:
        return 0.0
    trs = [abs(bars[i]["close"] - bars[i-1]["close"]) for i in range(-period, 0)]
    return float(np.mean(trs))

def high_n(bars: list[dict], n: int) -> float:
    closes = [b["close"] for b in bars[-(n+1):-1]]
    return max(closes) if closes else 0.0

def low_n(bars: list[dict], n: int) -> float:
    closes = [b["close"] for b in bars[-(n+1):-1]]
    return min(closes) if closes else float("inf")

def run():
    today   = date.today()
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    state   = load_state()
    equity  = state["equity"]
    positions = state["positions"]
    signals = []

    print(f"\n{'='*65}")
    print(f"  Crypto Breakout Trend v2 [4-SLOT] — {now_utc}")
    print(f"  Strategy: 25-day breakout / 8-day exit / 2.0x ATR")
    print(f"  Equity: ${equity:,.2f}  |  Positions: {len(positions)}/{MAX_POSITIONS}")
    print(f"{'='*65}")

    for symbol, info in TICKERS.items():
        display = info["display"]
        bars    = fetch_bars(symbol, info, limit=ENTRY_DAYS + 5)

        if len(bars) < ENTRY_DAYS + 2:
            held = " | POSITION HELD, exit check skipped" if symbol in positions else ""
            print(f"  {display}: insufficient data ({len(bars)} bars){held}")
            signals.append(f"⚠️ DATA FAIL {display} ({len(bars)} bars){held}")
            log_decision({
                "date": today, "ticker": display, "action": "DATA_FAIL",
                "close": None, "fill": None, "pnl": None,
                "equity": round(equity, 2),
                "reason": f"{len(bars)} bars{held}", "slots": "4slot",
            })
            continue

        today_open  = bars[-1]["open"]
        prev_close  = bars[-2]["close"]
        atr_val     = calc_atr(bars[:-1], ATR_PERIOD)
        entry_high  = high_n(bars[:-1], ENTRY_DAYS)
        exit_low    = low_n(bars[:-1], EXIT_DAYS)
        in_position = symbol in positions
        pos         = positions.get(symbol, {})

        if in_position:
            fill   = today_open * (1 - SLIPPAGE)
            stop   = pos["stop"]
            reason = None

            if prev_close < exit_low:
                reason = f"{EXIT_DAYS}d low break ({prev_close:.4f} < {exit_low:.4f})"
            elif prev_close <= stop:
                reason = f"ATR stop ({prev_close:.4f} <= {stop:.4f})"

            if reason:
                pnl = (fill - pos["entry_price"]) * pos["shares"] - COMMISSION
                equity += pos["cost"] + pnl
                equity = max(equity, 0.01)
                trade = {
                    "type": "CLOSE", "ticker": display,
                    "entry_date": pos["entry_date"], "exit_date": str(today),
                    "entry_price": pos["entry_price"], "exit_price": round(fill, 4),
                    "shares": pos["shares"], "pnl": round(pnl, 2),
                    "reason": reason, "equity": round(equity, 2),
                }
                state["trade_history"].append(trade)
                del positions[symbol]
                signals.append(f"🔴 [4s] CLOSE {display} @ ${fill:,.4f} | P&L ${pnl:+.2f} | {reason}")
                print(f"  {display}: EXIT — {reason} | P&L ${pnl:+.2f}")
                log_decision({
                    "date": today, "ticker": display, "action": "CLOSE",
                    "close": prev_close, "fill": round(fill, 4),
                    "pnl": round(pnl, 2), "equity": round(equity, 2),
                    "reason": reason, "slots": "4slot",
                })
                continue

            unrealised = (prev_close - pos["entry_price"]) * pos["shares"]
            print(f"  {display}: HOLD @ ${prev_close:,.4f} | stop ${stop:.4f} | unreal ${unrealised:+.2f}")
            log_decision({
                "date": today, "ticker": display, "action": "HOLD",
                "close": prev_close, "fill": None, "pnl": None,
                "equity": round(equity + unrealised, 2),
                "reason": f"unrealised ${unrealised:+.2f}", "slots": "4slot",
            })
            continue

        entry_signal = prev_close > entry_high
        print(f"  {display}: close={prev_close:.4f} | "
              f"{ENTRY_DAYS}d-high={entry_high:.4f} | "
              f"signal={'✓' if entry_signal else '✗'} | atr={atr_val:.4f}")

        if entry_signal and len(positions) < MAX_POSITIONS and atr_val > 0:
            fill      = today_open * (1 + SLIPPAGE)
            stop      = fill - ATR_MULT * atr_val
            risk_unit = fill - stop
            if risk_unit <= 0:
                continue

            shares = (equity * RISK_PCT) / risk_unit
            cost   = fill * shares + COMMISSION
            if cost > equity * 0.90:
                shares = (equity * 0.90 - COMMISSION) / fill
                cost   = fill * shares + COMMISSION
            if shares <= 0 or cost > equity:
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
            signals.append(f"🟢 [4s] ENTER {display} @ ${fill:,.4f} | stop=${stop:.4f}")
            print(f"  {display}: ENTRY @ ${fill:.4f} | shares={shares:.4f} | stop=${stop:.4f}")
            log_decision({
                "date": today, "ticker": display, "action": "ENTER",
                "close": prev_close, "fill": round(fill, 4), "pnl": None,
                "equity": round(equity, 2),
                "reason": f"{ENTRY_DAYS}d breakout", "slots": "4slot",
            })
        else:
            log_decision({
                "date": today, "ticker": display, "action": "NO_SIGNAL",
                "close": prev_close, "fill": None, "pnl": None,
                "equity": round(equity, 2),
                "reason": (f"no breakout" if not entry_signal
                           else f"max positions ({len(positions)}/{MAX_POSITIONS})"),
                "slots": "4slot",
            })

    total_trades = len(state["trade_history"])
    wins  = sum(1 for t in state["trade_history"] if t.get("pnl", 0) > 0)
    wr    = wins / total_trades * 100 if total_trades else 0
    total_pnl = sum(t.get("pnl", 0) for t in state["trade_history"])

    state["equity"]    = round(equity, 4)
    state["positions"] = positions
    state["last_run"]  = str(today)
    save_state(state)

    summary = (
        f"📊 LeapFrog v2 [4-slot] | {today}\n"
        f"Equity: ${equity:,.2f} | Pos: {len(positions)}/{MAX_POSITIONS}\n"
        f"Trades: {total_trades} | WR: {wr:.0f}% | P&L: ${total_pnl:+.2f}"
    )
    if signals:
        summary += "\n\nSignals:\n" + "\n".join(signals)
    else:
        summary += "\n\nNo signals — hunting."

    print(f"\n{summary}")
    # Don't notify — too noisy with two parallel systems. Remove comment to enable:
    # notify(summary)
    print(f"\n  State → {STATE_FILE} | Log → {LOG_FILE}\n")


if __name__ == "__main__":
    run()
