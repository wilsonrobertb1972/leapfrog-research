# Universe Expansion — Pre-Committed Criteria

**Status: FROZEN pending git commit. No edits after commit.**
**Date frozen: 2026-07-12**

---

## 0. Purpose

Increase signal frequency of Crypto Breakout Trend by adding assets, to compress the 30-signal paper gate from ~2 years to under 1 year. Strategy parameters are NOT under review.

## 1. What is frozen (unchanged, not tested)

| Parameter | Value |
|---|---|
| Entry | 55-day high breakout → fill next open |
| Exit | 10-day low break → fill next open |
| Stop | 2.0× ATR below entry |
| Risk/trade | 0.25% of equity |
| Bars | Daily |
| Max positions | 1 (scale to 2 after 20+ clean signals) — unchanged by expansion |

No per-asset parameter variation. Any asset that "would pass with 40/10" fails. Period.

## 2. Candidate inclusion criteria (applied BEFORE seeing any backtest result)

An asset enters the candidate list only if ALL hold:

1. **Venue:** listed spot on Kraken (matches execution infrastructure and US availability).
2. **Liquidity:** top 15 by 90-day average daily spot volume on Kraken as of 2026-07-12.
3. **History:** ≥ 5 full years of daily data on Binance public API (backtest data source), i.e. listed before Jul 2021. Must span the 2021 top → 2022 crash → 2023 recovery.
4. **Exclusions:** no stablecoins, no BTC/ETH wrappers or liquid-staking derivatives (WBTC, stETH, etc.), no exchange-collapse zombies (delisted or migrated tickers).

Candidate list is written down in full before any backtest. Assets cannot be added afterward.

**Expected candidates (verify against criteria at freeze):** BNB, XRP, ADA, DOGE, LINK, LTC, AVAX, DOT.

## 3. Backtest protocol (identical to original validation)

- Data: Binance daily klines, same loader as `backtest.py`.
- IS/OOS split: same boundaries as original validation (OOS 2022–2025).
- Costs: same slippage/fee assumptions; must also survive the 1% slippage stress.
- One run per asset at frozen parameters. No re-runs after "data fixes" unless the fix is documented and applied to all assets uniformly.

## 4. Acceptance floors (pre-committed — pass/fail, no judgment calls)

**Per asset (standalone, OOS):**
- Sharpe > 0.5
- Profit factor > 1.5
- Max DD better than the asset's own buy-and-hold max DD
- ≥ 8 OOS trades (fewer = insufficient evidence = fail, regardless of stats)

**Portfolio (all admitted assets + BTC/ETH/SOL, equal risk weighting):**
- Portfolio OOS Sharpe ≥ 1.15 (current 1.267 minus 0.117 tolerance, set 2026-07-12)
- Portfolio OOS Max DD ≤ 10%
- Leave-one-out: removing any single asset keeps portfolio OOS Sharpe > 1.0

**Failure handling:** failed assets are logged in this doc with their stats and never re-tested against these rules. No second looks, no "close enough."

## 5. Correlation & risk constraints (unchanged by expansion)

- Assume 3–4 effective independent bets regardless of universe size — alts are BTC beta in crashes.
- Max positions stays at 1 (→2 per existing schedule). Simultaneous signals: take the one with the largest breakout margin (% above its 55-day high); log the skipped signals.
- 0.25% risk/trade unchanged.
- Report pairwise correlation matrix of daily returns (OOS window) for the record — informational, not a gate.

## 6. Process rules

1. This doc is frozen (git commit in `leapfrog-research`) before `data.py` fetches a single candidate candle.
2. Results are accepted as they land. If zero assets pass, the universe stays BTC/ETH/SOL and that's the answer.
3. Paper trading on BTC/ETH/SOL continues uninterrupted throughout.
4. `paper_trader.py` universe updates only after all gates pass, as a single commit referencing this doc.
5. Paper-gate count: signals from new assets count toward the 30 only from their date of addition — no retroactive credit.

## 7. Decisions (set at freeze)

| Decision | Set to | Date |
|---|---|---|
| Execution venue for liquidity filter | Kraken | 2026-07-12 |
| Portfolio Sharpe floor | 1.15 | 2026-07-12 |
| Top-N volume cutoff | 15 | 2026-07-12 |

---

*All decisions set. Commit this file to leapfrog-research, then backtests may begin.*
