"""
data.py — Historical data fetcher for leapfrog-research
Sources:
  - Equities/ETFs: Yahoo Finance (yfinance)
  - Crypto: Binance public API (no key needed)

Usage:
  from data import get_daily
  df = get_daily("BTC-USD", "2018-01-01", "2024-01-01")
  df = get_daily("SPY",     "2010-01-01", "2024-01-01")
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)

# ── Ticker routing ─────────────────────────────────────────────────────────────
_CRYPTO = {
    "BTC-USD": "BTCUSDT",
    "ETH-USD": "ETHUSDT",
    "SOL-USD": "SOLUSDT",
    "AVAX-USD": "AVAXUSDT",
    "LINK-USD": "LINKUSDT",
    "XRP-USD":  "XRPUSDT",
    "DOGE-USD": "DOGEUSDT",
    "ADA-USD":  "ADAUSDT",
    "BNB-USD":  "BNBUSDT",
}

_EQUITY = [
    "SPY","QQQ","GLD","TLT","IWM","EFA","EEM","BIL",
    "USO","SH","SQQQ","NVDA","MSFT","AAPL",
    # Asian ETFs
    "EWJ","EWH","EWS","MCHI",
]


def get_daily(ticker: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
    """
    Fetch OHLCV daily bars for any ticker.
    Returns DataFrame with columns: open, high, low, close, volume
    Index: DatetimeIndex (UTC dates)
    """
    cache_key = f"{ticker}_{start}_{end}".replace("/", "-")
    cache_path = CACHE_DIR / f"{cache_key}.parquet"

    if use_cache and cache_path.exists():
        df = pd.read_parquet(cache_path)
        print(f"[cache] {ticker}: {len(df)} rows")
        return df

    if ticker in _CRYPTO:
        df = _fetch_binance(ticker, start, end)
    else:
        df = _fetch_yahoo(ticker, start, end)

    if df is not None and len(df) > 0:
        df.to_parquet(cache_path)
        print(f"[fetch] {ticker}: {len(df)} rows ({df.index[0].date()} → {df.index[-1].date()})")
    return df


def get_universe(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """Fetch multiple tickers. Returns dict of DataFrames."""
    result = {}
    for t in tickers:
        try:
            df = get_daily(t, start, end)
            if df is not None and len(df) > 10:
                result[t] = df
        except Exception as e:
            print(f"[error] {t}: {e}")
    return result


# ── Yahoo Finance ──────────────────────────────────────────────────────────────
def _fetch_yahoo(ticker: str, start: str, end: str) -> pd.DataFrame:
    try:
        import yfinance as yf
        raw = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if raw.empty:
            print(f"[yahoo] No data for {ticker}")
            return pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0].lower() for c in raw.columns]
        else:
            raw.columns = [c.lower() for c in raw.columns]
        raw.index = pd.to_datetime(raw.index, utc=True)
        return raw[["open","high","low","close","volume"]].dropna()
    except Exception as e:
        print(f"[yahoo] {ticker} error: {e}")
        return pd.DataFrame()


# ── Binance (crypto, no API key) ───────────────────────────────────────────────
def _fetch_binance(coinbase_ticker: str, start: str, end: str) -> pd.DataFrame:
    symbol = _CRYPTO[coinbase_ticker]
    start_ms = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms   = int(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp() * 1000)

    url    = "https://api.binance.com/api/v3/klines"
    rows   = []
    cursor = start_ms

    while cursor < end_ms:
        params = {
            "symbol":    symbol,
            "interval":  "1d",
            "startTime": cursor,
            "endTime":   end_ms,
            "limit":     1000,
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if not data or isinstance(data, dict):
                break
            for row in data:
                rows.append({
                    "open":   float(row[1]),
                    "high":   float(row[2]),
                    "low":    float(row[3]),
                    "close":  float(row[4]),
                    "volume": float(row[5]),
                    "ts":     int(row[0]),
                })
            cursor = data[-1][0] + 86400000  # next day
            if len(data) < 1000:
                break
            time.sleep(0.1)
        except Exception as e:
            print(f"[binance] {symbol} error: {e}")
            break

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df[["open","high","low","close","volume"]].sort_index()
    df = df[df.index < pd.Timestamp(end, tz="UTC")]
    return df


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Testing data fetcher...")
    tickers = ["SPY", "GLD", "BTC-USD", "ETH-USD"]
    for t in tickers:
        df = get_daily(t, "2020-01-01", "2024-01-01")
        if len(df):
            print(f"  {t:12s} {len(df)} bars  last_close={df['close'].iloc[-1]:.2f}")
        else:
            print(f"  {t:12s} NO DATA")
