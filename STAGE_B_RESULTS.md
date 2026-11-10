# Universe expansion v2: Stage B results (2026-11-10)

Criteria: UNIVERSE_EXPANSION_CRITERIA_v2.md (frozen, commit 871ad6c). Engine: stage_b.py, real-code replay of paper_trader.py. OOS 2022-01-01 to 2025-05-31, primary cost 0.5%/side.

## Per-asset (standalone, 1 slot)
PASS: ETH (Sharpe 0.74, PF 2.14, 22 trades), XRP (0.85, 3.77, 27), DOGE (0.81, 3.97, 22), ADA (0.55, 1.89, 26)
FAIL (Sharpe and PF): ZEC (0.19, 1.28), NEAR (0.19, 1.35), LINK (0.20, 1.24), UNI (0.23, 1.35), LTC (-0.16, 0.76)
Failed assets are logged and are never re-tested under this criteria set.

## Portfolio (live four + ETH, XRP, DOGE, ADA; 2 slots)
Sharpe 1.37 (>= 1.29 PASS), max DD -5.2% (<= 10% PASS), OOS trades 88 = 25.8/yr (>= 26 FAIL), PF 2.60.
Leave-one-out and stress cost not run (primary gate already failed).

## Informational (decides nothing)
4 slots on the expanded universe: Sharpe 1.07, DD -6.6%, 44.9 trades/yr.
OOS daily-return correlation of new coins with BTC: 0.56 to 0.84.

## Verdict
GATE FAILED (trade-rate gate, 25.8 vs 26). Universe stays BTC, SOL, NVDA, GLD. paper_trader.py unchanged.
Any follow-up is a new pre-registered test that discloses it was designed after seeing these results.
