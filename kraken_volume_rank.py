import csv, time, statistics
import requests

BASE = "https://api.kraken.com/0/public"
STABLE = {"USDT","USDC","DAI","PYUSD","USDG","EURC","USD1","TUSD","USDD","FDUSD","RLUSD","EURT","AUDT","EUR","GBP","AUD","CAD","CHF","JPY"}

def get(path, **params):
    for _ in range(5):
        r = requests.get(f"{BASE}/{path}", params=params, timeout=30).json()
        if not r.get("error"):
            return r["result"]
        if any("Too many" in e or "Rate" in e for e in r["error"]):
            time.sleep(10); continue
        return None
    return None

pairs, tick = get("AssetPairs"), get("Ticker")
usd = {k: v for k, v in pairs.items()
       if v.get("quote") in ("ZUSD", "USD") and v.get("status") == "online" and "wsname" in v
       and v["wsname"].split("/")[0] not in STABLE and "." not in v["wsname"].split("/")[0]}
pre = sorted(((float(tick[k]["p"][1]) * float(tick[k]["v"][1]), k, v["wsname"])
              for k, v in usd.items() if k in tick), reverse=True)[:100]
rows = []
for i, (v24, k, ws) in enumerate(pre, 1):
    res = get("OHLC", pair=k, interval=1440)
    time.sleep(1.2)
    if not res:
        continue
    data = [x for kk, x in res.items() if kk != "last"][0]
    days = data[-91:-1]
    avg = statistics.mean(float(d[5]) * float(d[6]) for d in days) if days else 0.0
    rows.append((avg, ws, len(days)))
rows.sort(reverse=True)
with open("kraken_volume_rank.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["rank", "pair", "avg_90d_usd_volume", "days_of_data"])
    for i, (a, ws, n) in enumerate(rows, 1):
        w.writerow([i, ws, round(a), n])
print(f"{'#':>3} {'pair':14}{'avg 90d USD vol':>18}{'days':>6}")
for i, (a, ws, n) in enumerate(rows[:30], 1):
    print(f"{i:>3} {ws:14}{a:>18,.0f}{n:>6}")
print("\nNVDA / GLD tokens found:")
for i, (a, ws, n) in enumerate(rows, 1):
    if "NVDA" in ws.upper() or "GLD" in ws.upper():
        print(f"  rank {i}: {ws}  avg 90d USD vol {a:,.0f}")
