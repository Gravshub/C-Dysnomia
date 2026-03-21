---
name: lp-status
description: "Check GIBS LP pair reserves, implied prices, and health across all pairs on PulseX. Read-only."
argument-hint: "[pair_address or token_symbol]"
user-invocable: true
disable-model-invocation: false
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
---

# /lp-status — GIBS LP Pair Health Check

Check reserves, implied prices, and health of all GIBS LP pairs on PulseX V1/V2. Read-only.

## Context Files — Read First

- `/opt/joystick/repo/CLAUDE.md` — GIBS LP pairs table (Part 2), DEX addresses
- `/opt/joystick/repo/scripts/Joystick/core/config.py` — factory/router addresses
- `/opt/joystick/repo/scripts/Joystick/oracle/price.py` — price query patterns
- `/opt/joystick/repo/scripts/Joystick/dashboard/chain_reader.py` — Multicall3 batching

## Dynamic Context

!`ls /opt/joystick/repo/scripts/Joystick/data/pair_registry.json 2>/dev/null && echo "pair_registry.json exists" || echo "pair_registry.json NOT FOUND"`

## Arguments

`$ARGUMENTS` can be:
- Empty — check ALL known GIBS pairs
- A pair address (0x...) — check that specific pair
- A token symbol (`FED`, `PRVX`, `WPLS`, etc.) — find and check the GIBS/TOKEN pair

## Key Addresses

```
GIBS_LAU         = 0x66a08aa12da955eb63d7ac121a88b2b210a07b03
WPLS             = 0xA1077a294dDE1B09bB078844df40758a5D0f9a27
FED              = 0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff
PRVX             = 0xf6f8db0aba00007681f8faf16a0fda1c9b030b11
PulseX V1 Factory = 0x1715a3E4A142d8b698131108995174F37aEBA10D
PulseX V2 Factory = 0x29eA7545DEf87022BAdc76323F373EA1e707C523
```

## Known GIBS LP Pairs

| Token | DEX | Pair Address |
|-------|-----|-------------|
| FED | V2 | `0xA2a7a2153136b6ee075335b979fb6ac033412e4d` |
| PRVX | V2 | `0x89d38bfbff92cfc3c9ab8368e2348aaad6c68c50` |
| WPLS, ATROPA, WM, DFM, PROOF_RES, ZHENG, VOID, PARADE, TLRz | V1/V2 | Discover via `getPair()` |

## Implementation

### Step 1: Discover Pairs
For each token, call `getPair(GIBS_LAU, token)` on both V1 and V2 factories.
- `getPair` selector: `0xe6a43905`
- Also check `data/pair_registry.json` if it exists

### Step 2: Read Reserves (batch via Multicall3)
For each pair address:
- `getReserves()` selector: `0x0902f1ac` → `(uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast)`
- `token0()` selector: `0x0dfe1681` → `address` (to know which reserve is GIBS)

### Step 3: Calculate Metrics
For each pair with non-zero reserves:
- **GIBS reserve**: amount of GIBS in pool
- **Partner reserve**: amount of partner token
- **Implied GIBS price**: `partner_reserve / gibs_reserve` (in partner token)
- **Implied GIBS/PLS price**: convert via partner/WPLS pair if available
- **Health**: `EMPTY` if either reserve is 0, `THIN` if GIBS < 5, `HEALTHY` if GIBS >= 5

### Step 4: Cross-Pair Consistency
Compare implied GIBS/PLS prices across all active pairs. Flag spreads > 5% as potential arb opportunities.

## RPC Details

- Use `https://rpc-pulsechain.g4mm4.io` for all reads
- Multicall3: `0xcA11bde05977b3631167028862bE2a173976CA11`
- NEVER send transactions

## Output Format

```
========================================
  GIBS LP STATUS — Block NNNNNN
========================================

GIBS Supply: N,NNN | GIBS in LP: N,NNN (NN%)

Pair             DEX  GIBS     Partner         GIBS/PLS    TVL (PLS)  Health
───────────────────────────────────────────────────────────────────────────────
GIBS/FED         V2   1,440    187,450 FED     195.73      562,340    HEALTHY
GIBS/PRVX        V2   229      7,484 PRVX      220.45      100,728    HEALTHY
GIBS/WPLS        V2   0        0 WPLS          —           0          EMPTY
...

─── Price Consistency ───
FED route:   195.73 PLS/GIBS
PRVX route:  220.45 PLS/GIBS
Spread:      12.6% ← ARB OPPORTUNITY

─── Summary ───
Active pairs:  N/11
Total GIBS in LP: N,NNN (NN.N% of supply)
Deepest pool: GIBS/FED (NNNK PLS TVL)
```
