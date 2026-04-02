# Bot Recon Report — 2026-04-02

On-chain recon of 3 active PulseChain bots + 1 GIBS-specific sniper.
Source: BlockScout TX history, RPC receipt tracing, selector analysis.

## Key Finding: GIBS LAU Sniper

**`0x65930aa7...`** (contract `0x73a43f88...`, started Mar 30, nonce 126)

Watches GIBS LAU self-balance. When our `primeGibs(17)` deposits 17 GIBS,
sniper calls `Purchase(GIBS_LAU, 17)` to extract them and sells on GIBS/WPLS V2.
~455 PLS profit per snipe. Caused 5 reverted TXs = 836 PLS wasted.

**Fix:** HarvestModuleV3 `primeAndSell()` — atomic prime+extract+sell in one TX.

## Gas Price Intelligence

| Bot | Avg Gas (Beats) | Above Floor | Error Rate |
|-----|-----------------|-------------|------------|
| BOT3 Loop | 811,115 | 8% | 0% |
| BOT2 Farmer | 1,056,907 | 41% | 0% |
| JOYSTICK (old) | 1,542,240 | 106% | 2% |
| Network floor | ~748,320 | — | — |

PulseChain has no MEV infrastructure. Floor + small fixed tip is sufficient.

## Bot Profiles

### BOT1 "Surgeon" — `0x8bc6070a...`
- Contract: `0x0d97b2ef...` (12,689 bytes, unverified)
- Nonce: 27,099 | PLS: 55,734
- Custom selector `0x8fbde3d5`, direct pair.swap() (no router)
- Trades Dysnomia: FED, DAI, ATROPA, AFFECTION, HEX
- Approved GIBS LAU — trades in our pairs

### BOT2 "Farmer" — `0xaeef1146...`
- No custom contract — direct calls to AFFECTION + CHEON
- Nonce: 4,288 in 4 days | PLS: 10,196,356
- 13-second TX cadence, 0% reverts
- 213/250 TXs → AFFECTION Generate() variants (public-good minting)
- 37/250 → CHEON.Su() (territory grinding — competes with E3 MERIDIAN)
- AFF balance = 0 (generates to contract self-balance, not to self)

### BOT3 "Loop Machine" — `0x4a0bcf8d...`
- Contract: `0xd50417da...` (2,323 bytes, unverified)
- Nonce: 59,027 | PLS: 126,216
- Selector `0x722d4e64`, 68-byte calldata, 50 iterations per TX
- 404 token transfers in one TX (FED/FDIC/DISMISSED mint loops)
- Lowest gas of all: avg 811K Beats (8% above floor)

## Execution Lessons

1. **Router-less swaps** (BOT1): Send tokens direct to pair, call swap(). Saves ~30K gas/hop.
2. **Fire-and-forget nonces** (BOT2): Increment locally, don't wait for receipts. 0% reverts on idempotent ops.
3. **Contract-level loops** (BOT3): One TX for 50 iterations. 21K base gas paid once vs 50x.
4. **Floor gas pricing** (BOT3): 811K Beats works on PulseChain. No need for priority tips.
5. **Atomic operations** (all): Zero revert rate across all 3 bots. Our 2% came from the sniper exploit gap.

## Actions Taken

| # | Action | Status |
|---|--------|--------|
| 1 | Gas recalibration (floor+12%) | Committed |
| 2 | HarvestModuleV3 primeAndSell | Committed (needs deploy) |
| 3 | Watchlist updated | Committed |
| 4 | Sim-before-send hardening | Committed |
