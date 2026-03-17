# Joystick Bot — Automated PLS Generation Framework

> **Parent context**: [`../../CLAUDE.md`](../../CLAUDE.md) (ecosystem, token mechanics, addresses)
> **Script inventory**: [`../CLAUDE.md`](../CLAUDE.md) (standalone scripts, shared patterns)
> **TGSv8 source**: `contracts/TGSv8.sol` (also in project knowledge as `TGSv8`)

---

## Mission

Generate PLS income via multiple automated engines to fund a PulseChain validator node (32M PLS deposit). The bot operates under the on-chain identity "Joey" (`|>JOYSTICK<|`), wallet `0x17367877aF5A8D0Eb33ba5689A880f696386E24D`.

**North star**: 32,000,000 PLS
**Current balance**: 1,979,625 PLS (block 26,040,668)
**Gas buffer**: Always maintain ≥100K PLS

---

## Package Structure

```
scripts/Joystick/
├── bot.py                  # Priority scheduler — ROI-ranked engine selection + profit compounder
├── __init__.py
├── requirements.txt        # web3, eth_abi, pycryptodome, requests
│
├── core/                   # Infrastructure layer
│   ├── config.py           # Single source of truth: addresses, thresholds, env vars
│   ├── chain.py            # Multicall3 batch reads, w3 provider management
│   ├── wallet.py           # Nonce management, balance checks
│   ├── executor.py         # TX building, signing, sending pipeline
│   ├── gas_guard.py        # Gas price ceiling, PLS buffer enforcement
│   ├── gas_oracle.py       # Gas price fetching and caching
│   ├── simulator.py        # eth_call simulation wrapper
│   ├── strategist.py       # Cross-engine strategy coordination
│   ├── event_logger.py     # Structured event logging (JSON-L)
│   ├── rpc_provider.py     # RPCPool with circuit breakers, tier-based routing
│   ├── rpc_compat.py       # RPC compatibility shims
│   └── split_swap.py       # Split-route swap optimization
│
├── oracle/                 # Market intelligence layer
│   ├── price.py            # getAmountsOut(), getReservesBoth() — DEX price queries
│   ├── scanner.py          # 272+ QING venue scanner
│   ├── profitability.py    # Uniswap v2 constant-product formula, profit calc
│   ├── route_auditor.py    # Multi-hop route profitability verification
│   ├── pair_discovery.py   # Automated LP pair discovery across factories
│   ├── graph.py            # Token graph for pathfinding
│   └── data_store.py       # Persistent data layer (JSON files)
│
├── engines/                # Income engines (each inherits EngineBase)
│   ├── base.py             # EngineBase ABC + EngineResult dataclass
│   ├── arb.py              # E1 RAZOR — cross-DEX QING arbitrage
│   ├── dss.py              # E2 CEREAL — chatAndClaim → GIBS → PLS
│   ├── beat.py             # E3 MERIDIAN — territory positioning
│   ├── token_factory.py    # E4 — WM minting + AFF BuyWith routes
│   ├── lau.py              # E5 ABUPRU — mathematical state loop + EmitSniper
│   ├── treasury_sniper.py  # E6 DaVINCI — batchClaimTreasury via recon
│   ├── spine_runner.py     # E7 BACKBONE — batchMintAndClaim on Deb=True
│   └── phreak.py           # E8 Phr3ak — Web Weaver (V4 deploy → mint → pair → burn % → arb cycle).
│
├── loops/                  # Game loop abstractions
│   ├── base.py             # GameLoopBase ABC
│   └── terraform.py        # Territory expansion loop
│
├── tools/                  # One-off utilities & test harnesses
│   ├── tgsv8_recon.py      # TGSv8 state inspection
│   ├── tgsv8_mint_test.py  # TGSv8 mint testing
│   ├── tgsv8_mint_wm_test.py  # WM mint test via TGSv8
│   └── archive/            # Superseded tools
│
├── tests/                  # Test suite
│   ├── conftest.py         # Pytest fixtures
│   ├── anvil_helpers.py    # Anvil fork helpers
│   ├── test_anvil_full.py  # Full integration tests on Anvil fork
│   ├── test_data_store.py  # Data store unit tests
│   ├── test_engines_5_6.py # E5/E6 unit tests
│   ├── test_razor_pulsechain.py  # E1 live PulseChain tests
│   ├── TEST_REPORT.md      # Test results documentation
│   └── README.md           # Test setup guide
│
└── data/                   # Runtime data (large files)
    ├── contracts.json       # Runtime address map
    ├── engine_state.json    # Persisted engine state (failure counts, etc.)
    ├── recon_results.json   # Treasury recon results (39K lines, 1.26 MB)
    ├── spine_map.json       # Spine opportunity map (860K)
    ├── spine_opportunities.json  # Ranked spine targets (338K)
    ├── spinetracker_raw.json    # Raw spine data (944K)
    ├── token_master.json    # Master token registry (574K)
    ├── pair_registry.json   # Known DEX pairs (543K)
    ├── branching_parents.json   # Token parent relationships (57K)
    ├── v2_federal_tokens.json   # V2 Federal token scan (5.5K)
    ├── phreak_config.json   # Phreak engine config
    ├── abis/                # Contract ABI JSON files
    ├── events/              # Event log output
    ├── JOYSTICK_v2_PLAN.md  # Treasury web exploitation plan
    ├── gibs_liquidity_strategy.md  # LP deployment strategy doc
    ├── build_log.md         # Build history
    └── treasury_recon.py    # Recon data generation script
```

---

## Implementation Rules

These are **non-negotiable** across all engines and core modules:

1. **Always simulate via `eth_call` before sending any TX** — use `simulator.py`
2. **Always `estimate_gas()` with 1.3x multiplier** — abort if it fails, never send blind
3. **Dual RPC**: `rpc-pulsechain.g4mm4.io` for reads, `rpc.pulsechain.com` for TX submit
4. **Gas denomination**: Beats (not Gwei). `1 PLS = 1,000,000,000 Beats`
5. **Gas price ceiling**: skip cycle if `gas_price > configured ceiling`
6. **100K PLS gas buffer**: never let wallet drop below this
7. **No OpenZeppelin imports** in Solidity — inline guards
8. **Atomic file writes**: `os.rename()` / `os.replace()` for data persistence
9. **Never rewrite existing scripts** — import as modules
10. **Chain ID 369** — always set explicitly
11. **Single RPC for critical TXs** — avoid RPCPool race ("replacement underpriced" bug)
12. **pycryptodome for keccak** — not pysha3 (unreliable)

---

## EngineBase Pattern

Every engine inherits from `engines/base.py`:

```python
class EngineBase(ABC):
    name: str = "UnnamedEngine"
    MAX_FAILURES: int = 3        # Circuit breaker threshold
    DISABLE_SECS: int = 600      # Re-enable after cooldown

    @abstractmethod
    def is_ready(self) -> bool:   # Read-only prereq check
    @abstractmethod
    def simulate(self) -> tuple[int, int]:  # (profit_wei, gas_wei) via eth_call
    @abstractmethod
    def execute(self, dry_run=False) -> EngineResult:  # Full TX, never raise

    def roi(self) -> float:       # profit/gas ratio for ranking
    def is_disabled(self) -> bool: # Circuit breaker check
```

```python
@dataclass
class EngineResult:
    success: bool
    profit_wei: int     # Actual PLS gained
    gas_wei: int        # Actual gas spent
    tx_hashes: list[str]
    notes: str = ""
    # Properties: profit_pls, gas_pls, net_pls
```

**Cycle flow** (in `bot.py`):
1. Check `gas_guard` — skip if gas too high or PLS too low
2. For each engine: `is_ready()` → `simulate()` → compute ROI
3. Rank by ROI, execute top profitable engine
4. Log result via `event_logger`
5. Compound profit (optional: auto-reinvest)

---

## Engine Status Summary (Block 26,040,668 — 2026-03-16)

| # | Name | File | Description | Status |
|---|------|------|-------------|--------|
| E1 | RAZOR (Arb) | `arb.py` | Cross-DEX QING arbitrage via TGSv8 `atomicArb()` | Ready — net-negative per recon |
| E2 | CEREAL (DSS) | `dss.py` | `chatAndClaim` / `chatAndClaimWithMultiplier(17)` → GIBS → PLS | **BLOCKED** — DSS has 0 GIBS |
| E3 | MERIDIAN (Beat) | `beat.py` | Territory positioning (`CHEON.Su` + `META.Beat`) | Running — Dione=41 |
| E4 | Token Factory | `token_factory.py` | TGSv8 `mintWM()` + AFFECTION BuyWith routes | **AFF DISABLED** — BuyWith unprofitable |
| E5 | LAU (ABUPRU) | `lau.py` | Mathematical state loop + EmitSniper | Gated — 150K PLS floor |
| E6 | DaVINCI (Treasury Sniper) | `treasury_sniper.py` | `batchClaimTreasury()` via recon data | Wired — needs recon targets (~1-10K PLS) |
| E7 | BACKBONE (Spine Runner) | `spine_runner.py` | `batchMintAndClaim()` on Debenture=True | Blocked — needs OZZY spine via E8 |
| E8 | PHR3AK (Web Weaver) | `phreak.py` | Token Web Manipulation Engine | Three modes -  Mode 1: DEPLOY Mode 2: ARM Mode 3: STITCH Mode | V4 deploy → mint → pair → burn % → arb cycle |

---

## Engine Details

### E1 — RAZOR (Cross-DEX Arbitrage)
**File**: `arb.py` (41K)
**Mechanism**: Scan 272+ QING venues for Purchase→DEX price discrepancies. Execute via TGSv8 `atomicArb()` for atomic cross-DEX swaps.
**Current**: Net-negative across all scanned pairs. V1 pools too shallow. Low priority.
**Triggers**: Price oracle detects >5% spread between any two DEX paths for same token.

### E2 — CEREAL (DSS Income)
**File**: `dss.py` (7.5K)
**Mechanism**: `chatAndClaimWithMultiplier(17)` on DSS → 18 GIBS per call → swap GIBS→PLS via GIBS/WPLS V2 pair.
**Economics**: GIBS at 195.73 PLS, break-even at ~21.5 PLS/GIBS = **9x above break-even**.
**Each cycle**: ~3,523 PLS gross before gas.
**Current**: **BLOCKED** — DSS has 0 GIBS balance. Needs refund or mint cycle.
**Addresses**:
- DSS: `0x91Df693177eE5C81016d0B7c4c2052A7d229c031`
- GIBS/WPLS V2 pair: `0x7BCa1c997c...`

### E3 — MERIDIAN (Territory Beat)
**File**: `beat.py` (6.5K)
**Mechanism**: `CHEON.Su(GIBS_QING)` → `META.Beat(GIBS_QING_WAAT)` → territory range/power computation.
**Prerequisites**: SHIO balances (Fornax, Fomalhaute, CHO) at GIBS_LAU and GIBS_QING.
**Current**: Running. Dione=41. WORLD not yet deployed on-chain.
**GIBS_QING_WAAT**: `251913148994206487765525643443518492465195287520927385378321984475167864513`

### E4 — Token Factory (WM + AFF Minting)
**File**: `token_factory.py` (32K)
**WM mode**: TGSv8 `mintWM(count)` → sell WM on DEX. Currently unprofitable (23 PLS cost vs 17 PLS DEX value).
**AFF mode**: DISABLED (`AFF_GENERATE_ENABLED = False`). `multiGenerate()` mints to contract self, not caller. BuyWith routes need AFF > 118 PLS to be profitable (currently ~50 PLS).
**Both modes**: Always-on background scan for profitable gas windows.

### E5 — LAU ABUPRU (Mathematical State Loop)
**File**: `lau.py` (35K)
**Mechanism**: Complex mathematical state transitions on LAU token + EmitSniper for event-driven opportunities.
**Gate**: 150K PLS floor — engine won't activate below this wallet balance.
**Current**: Gated. Wallet at 1.98M PLS (well above floor but engine is low priority).

### E6 — DaVINCI (Treasury Sniper)
**File**: `treasury_sniper.py` (12K)
**Mechanism**: TGSv8 `batchClaimTreasury()` on tokens with claimable backing > acquisition cost.
**Data**: `data/recon_results.json` (39K lines) — full treasury scan.
**Yield**: Realistic ~1-10K PLS after pool price impact.
**Needs**: Live claim simulation via `eth_call` (see `tools/claim_verifier.py` pattern from Session 10).
**Key finding**: All high-value targets are V3 Index Minter tokens (family-isolated Claim).

### E7 — BACKBONE (Spine Runner)
**File**: `spine_runner.py` (17K)
**Mechanism**: TGSv8 `batchMintAndClaim()` on Debenture=True tokens for infinite mint-claim loops.
**Data**: `data/spine_map.json`, `data/spine_opportunities.json`
**Current**: Only OZZY has Debenture=true in V2 Federal, but its PLS/token is near-zero (~1.54e-11).
**Blocked by**: E8 (Web Weaver) — need to deploy custom sibling tokens as ammo.

### E8 — PHR3AK (Web Weaver)
(fill this in)


---

## TGSv8 — Execution Substrate

**Address**: `0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32` (block 25,943,194)
**Source**: `contracts/TGSv8.sol`

### Key Capabilities

| Function | Purpose |
|----------|---------|
| `executeRoute(Step[])` | Atomic multi-step execution (MINT→CLAIM→SWAP chain) |
| `atomicArb(...)` | Cross-DEX arbitrage in one TX |
| `batchClaimTreasury(targets[])` | Sweep backing from N treasuries |
| `batchMintAndClaim(token, count)` | N mint-claim loops in one TX |
| `mintWM(count)` | Batch WM minting (no external dependency) |
| `createV4(name, symbol, mvAmount)` | Deploy V4 personal treasury token |
| `swapNativeForTokens(...)` | PLS → token via DEX |
| `swapTokensForNative(...)` | Token → PLS via DEX |
| `wrapPLS()` / `unwrapWPLS()` | WPLS conversion |
| `getReservesBoth()` | V1+V2 reserves in one call |
| `withdraw(token, amount)` | Withdraw tokens to owner |
| `withdrawPLS()` | Withdraw PLS to owner |

### Step Struct (executeRoute)
```solidity
struct Step {
    uint8 action;    // 0=swap, 1=mint, 2=claim, 3=approve
    address target;  // Contract to call
    uint8 dex;       // 0=V1, 1=V2 (per-step DEX selection)
    bytes data;      // Encoded function call
}
```

### TGSv8 Additions Over v7
- `mintWM(count)` — no TGSv5 dependency
- `getReservesBoth()` — dual-DEX oracle
- Per-step `dex` field in `executeRoute`
- Native PLS handling (wrap/unwrap/swap)

### Current State
```
TGSv8 PLS:  0
TGSv8 WM:   9
Owner:       Joey (0x1736...)
```

### Legacy Contracts (DO NOT USE)
- TGSv5 (`0xeeB330d3...`) — superseded
- TGSv7 (`0x82E8B7e2...`) — superseded (V4 2x transferFrom bug)

---

## PLS Generation Strategies

### Strategy A: DSS (E2) — HIGHEST CONFIDENCE
`chatAndClaimWithMultiplier(17)` → 18 GIBS → swap to PLS.
- GIBS: 195.73 PLS (9x above 21.5 PLS break-even)
- Per cycle: ~3,523 PLS gross
- **BLOCKED**: DSS has 0 GIBS — needs refund

### Strategy B: Treasury Sniping (E6)
Scan treasury tokens for claimable backing > acquisition cost.
Realistic yield: ~1-10K PLS per batch after pool impact.

### Strategy C: Spine Running (E7)
Infinite mint-claim loop on Debenture=True tokens.
Only OZZY Deb=true, near-zero PLS/token. Needs E8.

### Strategy D: V3 Family Exploitation (E8)
High-value targets: MXDAI (118 PLS/tok, 29M liq), S&㉿500 (44K PLS/tok, 6M liq).
Requires deploying sibling tokens in same V3 family as ammo.
Needs: MV tokens + parent token acquisition.

### Strategy E: Purchase→DEX Arb (E1)
AFFECTION-funded Purchase across 272 QINGs vs DEX. Currently net-negative.

### Strategy F: AFFECTION BuyWith Routes (E4
All routes converge to ~1 pDAI/AFF. AFF must trade >118 PLS for profit. Currently ~50 PLS. We monitor, we wait.
`multiGenerate()` is useless alone — only primes supply, doesn't deliver.
`multiBuyWith()` delivers but needs payment tokens at unprofitable exchange rates.

---

## Oracle System

### price.py
- `get_amounts_out(router, amount_in, path)` — DEX quote via Router
- `get_reserves_both(pair_v1, pair_v2)` — dual-DEX reserves via TGSv8

### scanner.py
- Scans 272+ QINGs discovered via MAP
- Checks `Purchase()` rates vs DEX prices per venue

### profitability.py
- Uniswap v2 constant-product formula: `amountOut = (amountIn * 997 * reserveOut) / (reserveIn * 1000 + amountIn * 997)`
- Accounts for 0.3% LP fee
- Computes net profit after gas estimation

### route_auditor.py
- Multi-hop route profitability verification
- AFF BuyWith route break-even analysis

### pair_discovery.py
- Scans PulseX V1/V2, 9mm, 9inch factories for pair existence
- Builds `pair_registry.json`

---

## Core Modules

### config.py — Address Registry
Single source of truth. All addresses as `Web3.to_checksum_address()`. Key entries:
- `JOEY_WALLET`, `GIBS_LAU`, `GIBS_QING`, `JOEY_YUE`, `DSS`
- `AFFECTION`, `WM`, `WPLS`, `PDAI`, `PUSDC`
- `META`, `CHEON`, `VOID`, `MAP_ADDR`, `CHOA`
- `PULSEX_V1_ROUTER`, `PULSEX_V1_FACTORY`, `PULSEX_V2_FACTORY`
- `NINEMM_FACTORY`, `NINEINCH_FACTORY`
- `TGSV8`, `JV8A`
- `GIBS_QING_WAAT` (constant)

### chain.py — Multicall3 Batching
Wraps `Multicall3` (`0xcA11bde05977b3631167028862bE2a173976CA11`) for batch reads:
```python
chain = Chain()
results = chain.multicall([(target1, data1), (target2, data2), ...])
```

### executor.py — TX Pipeline
```python
executor = Executor(wallet, gas_guard, simulator)
result = executor.send_tx(to, data, value=0, gas_limit=None)
# Internally: simulate → estimate_gas → sign → submit → wait for receipt
```

### gas_guard.py — Safety Rails
- Enforces gas price ceiling (skip cycle if too high)
- Enforces 100K PLS minimum wallet balance
- Returns `(should_proceed, reason)` tuple

### rpc_provider.py — RPCPool
Tiered RPC routing with circuit breakers:
- Tier 1 (read): `rpc-pulsechain.g4mm4.io`
- Tier 1 (submit): `rpc.pulsechain.com`
- Circuit breaker: N failures → cooldown period → auto-recovery
- **Known bug**: Multi-provider `send_raw()` causes "replacement underpriced" race. Use single RPC for critical TXs.

### event_logger.py
JSON-L structured logging to `data/events/`:
```python
events.log("engine.dss.success", engine="DSS", data={"profit_pls": 3523.4})
```

---

## Key Addresses (Runtime)

| Name | Address | Role |
|------|---------|------|
| Joey Wallet | `0x17367877aF5A8D0Eb33ba5689A880f696386E24D` | EOA |
| TGSv8 | `0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32` | Execution substrate |
| JV8A | `0x364793Ea48DEe0b5484F98235ABd1B5f996A0C30` | V4 treasury (unminted) |
| DSS | `0x91Df693177eE5C81016d0B7c4c2052A7d229c031` | DysnomiaSelfSnipev4 |
| GIBS LAU | `0x66a08aa12da955eb63d7ac121a88b2b210a07b03` | Player token |
| GIBS QING | `0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35` | Venue |
| Multi AFF | `0xCF138a83D739eE98D7A54159E94e5BFaa4B61988` | Batch AFF minter |
| GIBS/WPLS V2 | `0x7BCa1c997c...` | Price anchor pair |
| GIBS/FED V2 | `0xA2a7a2153136b6ee075335b979fb6ac033412e4d` | Deepest arb surface |

---

## GIBS LP Deployment (10 pairs — block 25,984,143)

| Pair | DEX | Address | Notes |
|------|-----|---------|-------|
| GIBS/WPLS | V2 | `0x7BCa1c997c...` | Price anchor |
| GIBS/FED | V2 | `0xA2a7a215...` | Deepest arb surface |
| GIBS/ATROPA | V1 | `0xa152659B...` | pDAI intermediate |
| GIBS/WM | V2 | `0xc23Cf1aF...` | |
| GIBS/DFM | V2 | `0x88c5B784...` | Thin |
| GIBS/PROOF_RES | V2 | `0xC52EFaed...` | |
| GIBS/ZHENG | V2 | `0xbFBEaf50...` | |
| GIBS/VOID | V2 | `0xB0776024...` | |
| GIBS/PARADE | V2 | `0xD8dA05aF...` | Thin |
| GIBS/TLRz | V2 | `0x7711f0dE...` | Thin |

87% of GIBS supply (3,396 total) in LP. Joey holds 0 GIBS in wallet. AMM bots actively arb between pairs — fees accumulate on both sides.

---

## Current State (Block 26,040,668 — 2026-03-16)

### Wallet
```
PLS:        1,979,625        Nonce:  128
GIBS:       0 (all in LP)    WM:     263.15
AFF:        127.18           ATROPA: 166.78
VOID:       51.22            FED:    0.04
```

### TGSv8
```
PLS:  0        WM:  9
```

### Market
```
GIBS:     195.73 PLS         GIBS supply:  3,396
PLS/USD:  ~$0.0150           DSS GIBS:     0
Gas:      ~748K Beats
```

### Engine Readiness
```
E1 RAZOR:      Ready — net-negative, low priority
E2 CEREAL:     BLOCKED — 0 GIBS in DSS
E3 MERIDIAN:   Running — Dione=41
E4 Factory:    AFF — BuyWith unprofitable; WM unprofitable
E5 ABUPRU:     Gated — 150K floor (wallet OK, low priority)
E6 DaVINCI:    Wired — needs live recon targets
E7 BACKBONE:   Ready
E8 PHR3AK:     Ready
```

---

## Revenue Projections (from JOYSTICK_v2_PLAN.md)

| Target | PLS/hour | PLS/block |
|--------|----------|-----------|
| Minimum | 1,000,000 | 2,778 |
| Goal | 2,880,000 | 8,000 |

DSS at max capacity: ~184K PLS/hour. Real volume comes from treasury web engines (E6/E7/E8).

---

## Running the Bot

```bash
cd scripts/Joystick
export JOEY_PK="0x..."
export PULSECHAIN_READ_RPC="https://rpc-pulsechain.g4mm4.io"
export PULSECHAIN_RPC="https://rpc.pulsechain.com"

pip install -r requirements.txt
python3 bot.py           # Full scheduler
python3 -m bot           # Module mode
```

### Environment Variables (from config.py)
```
JOEY_PK              — Private key (required)
PULSECHAIN_RPC        — Submit RPC (default: rpc.pulsechain.com)
PULSECHAIN_READ_RPC   — Read RPC (default: rpc-pulsechain.g4mm4.io)
RPC_READ_TIMEOUT      — Read timeout secs (default: 30)
RPC_SUBMIT_TIMEOUT    — Submit timeout secs (default: 60)
RPC_MAX_RETRIES       — Max retries (default: 2)
RPC_CB_THRESHOLD      — Circuit breaker threshold (default: 5)
RPC_COOLDOWN_BASE     — Cooldown base secs (default: 30)
```

---

## What's Next

1. **Unblock E2** — DSS needs GIBS. Fund via chatAndClaim cycle or direct transfer.
2. **E4 background monitoring** — scan for WM and AFF price crossover windows
3. **E6 live recon** — eth_call simulation of top treasury targets with current prices
4. **E8 Web Weaver** — deploy V3 sibling tokens as ammo for MXDAI/S&㉿500
5. **E3 dual-mode** — integrate AFF minting alongside WM in token_factory.py

**Last Updated**: 2026-03-16 (block 26,040,668)
**Status**: OPERATIONAL. E2 blocked (0 GIBS in DSS). AFF routes unprofitable. E3 running.
