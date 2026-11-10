# Universe Expansion v2 — Pre-Committed Criteria

**Status: DRAFT until committed. No edits after commit.**
**Date frozen: 2026-11-10**
**Supersedes v1 (commit 38b12bf). v1 stays in the repo, unedited, as history.**

---

## 0. Purpose

Raise the closed-trade frequency of the live paper strategy by adding independent breakout opportunities, to reach the 30-trade gate sooner. Strategy parameters are NOT under review.

## 1. Why v2 exists

v1 specified 55/10 entry/exit, 1 position, and a 1.267 baseline. The paper trader runs 25/8/2.0x with 2 slots. v2 aligns the expansion test with what is running, and replaces the 0.1% slippage assumption with Kraken-level costs. The live trading venue is undecided; Kraken is used only as the liquidity and cost reference.

## 2. What is frozen (matches paper_trader.py as run)

| Parameter | Value |
|---|---|
| Entry | close > highest close of prior 25 days; fill at next open |
| Exit | close < lowest close of prior 8 days; fill at next open |
| Stop | entry minus 2.0 x ATR, ATR = 20-day mean absolute close-to-close change (as implemented) |
| Risk per trade | 0.25% of cash equity |
| Slots | 2 (primary). 4 slots reported, informational only |
| Costs, primary | 0.5% per side (maker fee 0.40% at Kraken tier 1, plus slippage) + $1 commission |
| Costs, stress | 0.9% per side (taker fee 0.80% at Kraken tier 1, plus slippage) + $1 commission |
| Signal priority | order of the universe list: live four first, then admitted candidates in 90-day volume rank. The code takes the first signal in list order |

No per-asset parameter variation. An asset that "would pass with other numbers" fails.

## 3. Baseline (live four: BTC-USD, SOL-USD, NVDA, GLD; real-code replay; 2 slots; OOS 2022-01-01 to 2025-05-31)

| Cost per side | Sharpe | Max DD | PF | OOS trades |
|---|---|---|---|---|
| 0.5% (primary) | 1.42 | -4.5% | 2.78 | 72 (about 21.1/yr) |
| 0.9% (stress) | 0.97 | -8.0% | 1.85 | 82 |

Source: slots_replay.py, output in cost_baseline_out.txt (committed with this doc).

## 4. Candidate inclusion (applied BEFORE any backtest; crypto only this round)

A candidate must satisfy ALL:
1. Listed spot on Kraken (used as the liquidity reference for the ranking). Tradability on the eventual live venue is NOT a research criterion: it is checked at the funding gate, and an asset that cannot be traded there is excluded from live trading without changing any research result.
2. Top 15 by 90-day average daily USD-pair volume on Kraken at the freeze date. Ranking run 2026-11-10 (kraken_volume_out.txt, kraken_volume_rank.csv, committed with this doc).
3. At least 5 full years of daily data in the backtest data source (Binance spot via data.py, api.binance.com), spanning the 2021 top, 2022 crash and 2023 recovery. Verified from the first available candle at fetch time; an asset that fails is logged as an exclusion and never re-tested.
4. Not a stablecoin, wrapper, liquid-staking derivative, or delisted/migrated ticker.
5. Not already in the live universe (BTC, SOL).

**Candidate list (frozen; no additions after commit):**
ETH, XRP, ZEC, NEAR, DOGE (Kraken ticker XDG), ADA, LINK, UNI, LTC

**Excluded before any fetch, with reasons (logged, never re-tested):**
- HYPE, SUI, TAO: listed after Jul 2021 (fail criterion 3)
- QNT: listing date unverified (fails by the rule "if in doubt, out")
- BNB, AVAX, DOT: not in the Kraken top 15 by 90-day volume
- PUMP, XMR, XLM, ENA and everything below rank 15: not top 15

**Disclosure:** ETH data was fetched during earlier research and is in data_cache. A prior NVDA/ETH/QQQ check showed ETH alone at OOS Sharpe 0.85, PF 2.57, 22 trades. Recorded here; ETH still runs through the same protocol as every other candidate.

## 5. Backtest protocol

- Engine: real-code replay of paper_trader.py logic (NOT nvda_check.py, which trades equities on weekends).
- Data: same loader the paper research uses (data.py). IS 2018-01-01 to 2021-12-31. OOS 2022-01-01 to 2025-05-31.
- One run per asset at frozen parameters and primary cost. No re-runs unless a bug fix is documented and applied to all assets uniformly.

## 6. Acceptance floors (pass/fail, no judgment calls)

**Per asset (standalone, 1 slot, OOS, primary cost):**
- Sharpe > 0.5
- Profit factor > 1.5
- Max DD better than the asset's own buy-and-hold max DD over the same OOS window
- At least 8 OOS trades (fewer = insufficient evidence = fail)

**Portfolio (live four + all assets that passed per-asset floors), 2 slots, OOS:**
- Primary cost: Sharpe >= 1.29 (0.908 x 1.42; same relative tolerance as v1)
- Primary cost: max DD <= 10%
- Primary cost, leave-one-out: removing any single admitted candidate keeps Sharpe >= 1.12 (0.789 x 1.42; v1 ratio)
- Primary cost: OOS trades/yr >= 26 (1.25 x baseline 21.1). Otherwise the expansion is not worth the added complexity
- Stress cost (0.9%): portfolio OOS Sharpe >= 0.88 (0.908 x 0.97)

**Failure handling:** failed assets are logged in this doc with their stats and never re-tested against these rules. No second looks.

## 7. Informational (not gates)
- Pairwise correlation matrix of daily returns, OOS window
- 4-slot results for the same universe

## 8. Process rules
1. Cache check run 2026-11-10: only ETH-USD files present (earlier research, disclosed above). No other candidate files existed before this doc.
2. This doc is committed before data.py fetches a single candidate candle.
3. Results are accepted as they land. If nothing passes, the universe stays as is and that is the answer.
4. Paper trading continues uninterrupted throughout.
5. paper_trader.py universe changes only after all gates pass, as a single commit referencing this doc.
6. New assets count toward the 30-trade gate only from their date of addition.

## 9. Decisions confirmed before commit
- [x] Cache checked: only ETH present, disclosed
- [x] Venue undecided: Kraken is the liquidity and cost reference only; venue is decided before the funding gate
- [x] Trade-rate gate (>= 26/yr) accepted
- [x] Cost levels (0.5% primary, 0.9% stress; Kraken tier 1 as a proxy) accepted; re-check against the actual venue before funding
- [x] Crypto-only this round accepted
