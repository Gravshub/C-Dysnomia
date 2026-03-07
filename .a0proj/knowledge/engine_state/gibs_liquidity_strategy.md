# GIBS Liquidity Strategy

Generated: 2026-03-05 by Claude Code (pre-query baseline — run `python scripts/gibs_pair_creator.py --query` for live data)

## On-Chain State (from session logs)

- GIBS totalSupply: ~3,361
- GIBS Joey holds: ~3,359
- AFFECTION Joey: ~88
- PLS balance: ~41,248
- 1 AFFECTION price: TBD (run --query for live rate)

## Existing GIBS Pairs

- GIBS/WPLS_V1: NONE
- GIBS/WPLS_V2: NONE
- GIBS/AFFECTION_V1: NONE
- GIBS/AFFECTION_V2: NONE
- GIBS/ATROPA_V1: NONE
- GIBS/ATROPA_V2: NONE

## Option A — GIBS / WPLS (PulseX V1)

The original plan. Clean, simple, enables Engine 2 (DSS) immediately.

- Pro: Unlocks chatAndClaim profit loop (18 GIBS per call at multiplier 17)
- Pro: DSS cycle becomes a single executeRoute call
- Con: GIBS priced in PLS — if PLS pumps, GIBS gets arbed out
- Implied initial ratio: ~21.5 PLS/GIBS (DSS break-even)

## Option B — GIBS / AFFECTION

Intra-ecosystem pair. Prices GIBS in game tokens.

- Pro: Value cycling within Dysnomia economy
- Pro: TGSv8.atomicArb() can exploit two-leg spread
- Con: Joey only has 88 AFFECTION — locking in LP means less arb capital
- Con: Does NOT unlock Engine 2 DSS directly

## Option C — GIBS / Atropa Tokens

Broadest play — connects GIBS into the maria token web.

- ATROPA: TBD (run --query)
- TBILL: TBD (run --query)
- HAR: TBD (run --query)
- Pro: GIBS becomes a node in the Atropa tree
- Con: Varying liquidity depth — higher pool impact risk

## RECOMMENDATION

Given:
- Joey PLS balance: ~41,248 (BELOW 100K buffer target)
- GIBS balance: ~3,359
- AFFECTION balance: ~88 (primary arb fuel for Engine 1)
- Engine 2 DSS blocked: YES

Recommended pair: **Option A (GIBS/WPLS)** — but **WAIT**
Reason: PLS balance (41,248) is below the 100K gas buffer floor.
  Creating LP now would further reduce PLS reserves below safe operating level.
  Wait until PLS > 100K, then create GIBS/WPLS to unlock DSS immediately.
Timing: WAIT until 100K PLS buffer restored
AFFECTION lock risk: LOW (Option A does not lock AFFECTION)
