"""fetch_candidates.py - Stage A of the v2 expansion test (criterion 3 only).
Fetches candidate daily history via data.get_daily (Binance) and checks history length.
Unmapped tickers are NOT fetched (get_daily would fall back to Yahoo, violating the frozen data source).
NO backtests, NO performance numbers. Frozen doc: UNIVERSE_EXPANSION_CRITERIA_v2.md (871ad6c)."""
import csv
import pandas as pd
import data

CANDS = ["ETH-USD", "XRP-USD", "ZEC-USD", "NEAR-USD", "DOGE-USD", "ADA-USD", "LINK-USD", "UNI-USD", "LTC-USD"]
START, END = "2018-01-01", "2025-06-01"
CUTOFF = pd.Timestamp("2021-07-01")

print("\nBinance symbol mapping in data._CRYPTO:")
for t in CANDS:
    print(f"  {t:10} -> {data._CRYPTO.get(t, 'NOT MAPPED')}")

rows = []
for t in CANDS:
    if t not in data._CRYPTO:
        rows.append((t, 0, "", "", "", "", "NOT MAPPED (not fetched)"))
        continue
    try:
        df = data.get_daily(t, START, END)
    except Exception as e:
        rows.append((t, 0, "", "", "", "", f"ERROR: {str(e)[:60]}"))
        continue
    if df is None or len(df) == 0:
        rows.append((t, 0, "", "", "", "", "NO DATA"))
        continue
    idx = pd.to_datetime(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    first, last = idx.min(), idx.max()
    missing = (last - first).days + 1 - len(idx)
    nans = int(df["close"].isna().sum()) if "close" in df.columns else -1
    status = "PASS" if first <= CUTOFF else "FAIL (history too short)"
    rows.append((t, len(idx), first.date(), last.date(), missing, nans, status))

print(f"\n{'ticker':10}{'rows':>6}  {'first':12}{'last':12}{'missing':>8}{'NaNs':>6}  status")
for r in rows:
    print(f"{r[0]:10}{r[1]:>6}  {str(r[2]):12}{str(r[3]):12}{str(r[4]):>8}{str(r[5]):>6}  {r[6]}")
with open("candidate_eligibility.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["ticker", "rows", "first", "last", "missing_days", "nans", "status"])
    w.writerows(rows)
print("\nWrote candidate_eligibility.csv")
