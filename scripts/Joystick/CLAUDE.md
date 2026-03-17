# Joystick V2 — Automated PLS Generation Framework

> **Parent context**: [`../../CLAUDE.md`](../../CLAUDE.md) (ecosystem, token mechanics, addresses)
> **Script inventory**: [`../CLAUDE.md`](../CLAUDE.md) (standalone scripts, shared patterns)
> **TGSv8 source**: `contracts/TGSv8.sol` (also in project knowledge as `TGSv8`)
> **Branch**: `claude/joystick-V2-FanxJ`

---

## Mission

Generate PLS income via 8 automated engines to fund a PulseChain validator node (32M PLS deposit). The bot operates under the on-chain identity "Joey" (`|>JOYSTICK<|`), wallet `0x17367877aF5A8D0Eb33ba5689A880f696386E24D`.

**North star**: 32,000,000 PLS
**Current balance**: 1,979,625 PLS (block 26,041,473)
**Gas buffer**: Always maintain ≥100K PLS

---

## V2 Architecture — 3-Wallet Parallel Pipeline

Joystick V2 runs a **3-wallet parallel pipeline** with async orchestration. Each wallet has a dedicated role, its own nonce tracker, and executes independently:

| Wallet | Role | Engines | Env Var |
|--------|------|---------|---------|
| **Joey** | Identity + orchestrator | E2 DSS, E3 Beat, E5 LAU | `DYSNOMIA_PRIVATE_KEY` (required) |
| **Minter** | Production | E4 Factory, E6 DaVINCI, E7 BACKBONE, E8 PHR3AK | `MINTER_PRIVATE_KEY` (optional) |
| **Seller** | Liquidation + arb | E1 RAZOR | `SELLER_PRIVATE_KEY` (optional) |

**Graceful degradation**: If Minter/Seller keys are not set, the bot falls back to single-wallet mode (Joey only). All engines route through Joey.

**Sweep**: When Seller PLS balance exceeds `SWEEP_THRESHOLD` (default 500K PLS), excess is swept to Joey automatically.

### Per-Cycle Flow (V2)

```
0. Multicall balance snapshot (all 3 wallets, 1 RPC call)
1. Gas guard — abort if PLS < 100K floor
2. Nonce reset for all wallets
3. Parallel simulate — all 8 engines via ThreadPoolExecutor (~300ms)
4. Strategist V2 evaluate — returns CycleRecommendation (up to 3 actions)
5. Parallel wallet execution — asyncio.gather() across wallets
6. Record results, sell queue update, sweep check
7. Gameplay loops (Terraform, etc.)
```

---

## Package Structure

```
scripts/Joystick/
├── bot.py                  # V2 orchestrator — 3-wallet async pipeline
├── __init__.py
├── requirements.txt        # web3, eth_abi, pycryptodome, requests, python-dotenv
│
├── core/                   # Infrastructure layer
│   ├── config.py           # Single source of truth: addresses, thresholds, env vars
│   ├── chain.py            # Multicall3 batch reads, w3 provider management
│   ├── wallet.py           # Legacy nonce management, balance checks
│   ├── wallet_manager.py   # V2: Multi-wallet config, per-wallet nonce, sweep logic
│   ├── executor.py         # TX building, signing, sending pipeline
│   ├── gas_guard.py        # Gas price ceiling, PLS buffer enforcement
│   ├── gas_oracle.py       # Gas price fetching and caching
│   ├── simulator.py        # eth_call simulation wrapper
│   ├── strategist.py       # V2: CycleRecommendation, rotation penalty, unlock bonuses
│   ├── concurrency.py      # V2: SimExecutor (parallel simulate + parallel execute)
│   ├── sell_queue.py       # V2: Track TGSv8 token balances for Seller liquidation
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
│   ├── base.py             # EngineBase ABC + EngineResult + SimResult dataclasses
│   ├── arb.py              # E1 RAZOR — cross-DEX QING arbitrage         [Seller]
│   ├── dss.py              # E2 CEREAL — chatAndClaim → GIBS → PLS       [Joey]
│   ├── beat.py             # E3 MERIDIAN — territory positioning          [Joey]
│   ├── token_factory.py    # E4 FACTORY — AFF multiBuyWith + WM mint     [Minter]
│   ├── lau.py              # E5 ABUPRU — math state loop + EmitSniper    [Joey]
│   ├── treasury_sniper.py  # E6 DaVINCI — batchClaimTreasury via recon   [Minter]
│   ├── spine_runner.py     # E7 BACKBONE — batchMintAndClaim on Deb=True [Minter]
│   └── phreak.py           # E8 PHR3AK — token web manipulation          [Minter]
│
├── loops/                  # Game loop abstractions
│   ├── base.py             # GameLoopBase ABC
│   └── terraform.py        # Territory expansion loop
│
├── tools/                  # One-off utilities & test harnesses
│   ├── tgsv8_recon.py      # TGSv8 state inspection
│   ├── tgsv8_mint_test.py  # TGSv8 mint testing
│   ├── tgsv8_mint_wm_test.py  # WM mint test via TGSv8
│   ├── test_aff_wm_cycle.py   # AFF+WM cycle profitability test
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
└── data/                   # Runtime data
    ├── contracts.json       # Runtime address map
    ├── engine_state.json    # Persisted engine state
    ├── phreak_config.json   # E8 PHR3AK configuration
    ├── recon_results.json   # Treasury recon (39K lines, 1.26 MB)
    ├── spine_map.json       # Spine opportunity map (860K)
    ├── spine_opportunities.json  # Ranked spine targets (338K)
    ├── spinetracker_raw.json    # Raw spine data (944K)
    ├── token_master.json    # Master token registry (574K)
    ├── pair_registry.json   # Known DEX pairs (543K)
    ├── branching_parents.json   # Token parent relationships (57K)
    ├── v2_federal_tokens.json   # V2 Federal token scan (5.5K)
    ├── abis/                # Contract ABI JSON files
    ├── events/              # Event log output (incl. phreak.json)
    ├── intel/               # Competitive intelligence
    │   ├── watchlist.json           # Competitor wallet watchlist
    │   ├── affection_minting_report_2026.json  # AFF minting landscape
    │   ├── affection_minter_profiles.json      # Bot operator profiles
    │   ├── affection_txs_2026_raw.json         # Raw TX data
    │   └── gas_efficiency_reference.json       # Gas benchmarks
    ├── JOYSTICK_v2_PLAN.md  # Treasury web exploitation plan
    ├── gibs_liquidity_strategy.md  # LP deployment strategy
    ├── build_log.md         # Build history
    └── treasury_recon.py    # Recon data generation script
```

---

## Implementation Rules

Non-negotiable across all engines and core modules:

1. **Always simulate via `eth_call` before sending any TX** — use `simulator.py`
2. **Always `estimate_gas()` with 1.3x multiplier** — abort if it fails, never send blind
3. **Dual RPC**: `rpc-pulsechain.g4mm4.io` for reads, `rpc.pulsechain.com` for TX submit
4. **Gas denomination**: Beats (not Gwei). `1 PLS = 1,000,000,000 Beats`
5. **Gas price ceiling**: skip cycle if `gas_price > GAS_PRICE_CEIL` (default 2M Gwei)
6. **100K PLS gas buffer**: never let any wallet drop below its floor
7. **No OpenZeppelin imports** in Solidity — inline guards
8. **Atomic file writes**: `os.rename()` / `os.replace()` for data persistence
9. **Never rewrite existing scripts** — import as modules
10. **Chain ID 369** — always set explicitly
11. **Single RPC for critical TXs** — avoid RPCPool race ("replacement underpriced" bug)
12. **pycryptodome for keccak** — not pysha3 (unreliable)

---

## EngineBase Pattern (V2)

Every engine inherits from `engines/base.py`:

```python
class EngineBase(ABC):
    name: str = "UnnamedEngine"
    MAX_FAILURES: int = 3        # Circuit breaker threshold
    DISABLE_SECS: int = 600      # Re-enable after cooldown

    @abstractmethod
    def is_ready(self) -> bool:        # Read-only prereq check
    @abstractmethod
    def simulate(self) -> tuple[int, int]:  # (profit_wei, gas_wei) via eth_call
    @abstractmethod
    def execute(self, dry_run=False) -> EngineResult:  # Full TX, never raise

    def roi(self) -> float:            # profit/gas ratio for ranking
    def sim_result(self) -> SimResult:  # V2: normalized SimResult with metadata
    def is_disabled(self) -> bool:      # Circuit breaker check
    @property
    def display_name(self) -> str:      # "E1 RAZOR", "E8 PHR3AK", etc.
    @property
    def wallet_role(self) -> str:       # "joey" | "minter" | "seller"
```

### SimResult (V2)
```python
@dataclass
class SimResult:
    success: bool = True
    profit_wei: int = 0
    gas_wei: int = 0
    pool_impact_pct: float = 0.0
    mode: str = ""              # e.g. "arm", "deploy", "stitch"
    confidence: float = 1.0     # engine self-assessed 0.0-1.0
    notes: str = ""
    wallet_role: str = ""       # determines which wallet executes
```

### EngineResult
```python
@dataclass
class EngineResult:
    success: bool
    profit_wei: int        # Actual PLS gained
    gas_wei: int           # Actual gas spent
    tx_hashes: list[str]
    notes: str = ""
    # Properties: profit_pls, gas_pls, net_pls
```

### Engine Display Names & Wallet Roles
```python
ENGINE_DISPLAY_NAMES = {
    "Arb": "E1 RAZOR",  "DSS": "E2 CEREAL",  "Beat": "E3 MERIDIAN",
    "TokenFactory": "E4 FACTORY",  "LAU": "E5 ABUPRU",
    "TreasurySniper": "E6 DaVINCI",  "SpineRunner": "E7 BACKBONE",
    "PHR3AK": "E8 PHR3AK",
}
ENGINE_WALLET_ROLES = {
    "Arb": "seller",  "DSS": "joey",  "Beat": "joey",
    "TokenFactory": "minter",  "LAU": "joey",
    "TreasurySniper": "minter",  "SpineRunner": "minter",
    "PHR3AK": "minter",
}
```

---

## Engine Status Summary (Block 26,041,473 — 2026-03-16)

| # | Name | File | Wallet | Description | Status |
|---|------|------|--------|-------------|--------|
| E1 | RAZOR (Arb) | `arb.py` (41K) | Seller | Cross-DEX QING arbitrage via TGSv8 `atomicArb()` | Ready — net-negative per recon |
| E2 | CEREAL (DSS) | `dss.py` (7.5K) | Joey | `chatAndClaimWithMultiplier(17)` → GIBS → PLS | **BLOCKED** — DSS has 0 GIBS |
| E3 | MERIDIAN (Beat) | `beat.py` (6.5K) | Joey | Territory positioning (`CHEON.Su` + `META.Beat`) | Running — Dione=41 |
| E4 | FACTORY | `token_factory.py` (50K) | Minter | AFF `multiBuyWith` all 5 routes + TGSv8 `mintWM()` | **AFF DISABLED** — BuyWith unprofitable |
| E5 | ABUPRU (LAU) | `lau.py` (35K) | Joey | Mathematical state loop + EmitSniper | Gated — 150K PLS floor |
| E6 | DaVINCI (Treasury Sniper) | `treasury_sniper.py` (12K) | Minter | `batchClaimTreasury()` via recon data | Wired — needs recon targets |
| E7 | BACKBONE (Spine Runner) | `spine_runner.py` (17K) | Minter | `batchMintAndClaim()` on Debenture=True | Blocked — needs E8 ARM |
| **E8** | **PHR3AK** | **`phreak.py` (47K)** | **Minter** | **Token web manipulation (ARM/DEPLOY/STITCH)** | **Ready — ARM mode critical path** |

---

## Engine Details

### E1 — RAZOR (Cross-DEX Arbitrage) `[Seller]`
**File**: `arb.py` (41K)
**Mechanism**: Scan 272+ QING venues for Purchase→DEX price discrepancies. Execute via TGSv8 `atomicArb()`.
**Current**: Net-negative across all scanned pairs. V1 pools too shallow.
**Triggers**: Price oracle detects >5% spread between any two DEX paths.

### E2 — CEREAL (DSS Income) `[Joey]`
**File**: `dss.py` (7.5K)
**Mechanism**: `chatAndClaimWithMultiplier(17)` on DSS → 18 GIBS per call → swap GIBS→PLS via GIBS/WPLS V2 pair.
**Economics**: GIBS at 195.73 PLS, break-even at ~21.5 PLS/GIBS = **9x above break-even**.
**Per cycle**: ~3,523 PLS gross before gas.
**Current**: **BLOCKED** — DSS has 0 GIBS balance. Needs refund or mint cycle.
**Key addresses**: DSS `0x91Df6931...`, GIBS/WPLS V2 `0x7BCa1c997c...`

### E3 — MERIDIAN (Territory Beat) `[Joey]`
**File**: `beat.py` (6.5K)
**Mechanism**: `CHEON.Su(GIBS_QING)` → `META.Beat(GIBS_QING_WAAT)` → territory computation.
**Prerequisites**: SHIO balances (Fornax, Fomalhaute, CHO) at GIBS_LAU and GIBS_QING.
**Current**: Running. Dione=41. WORLD not yet deployed.
**Strategic**: Always valid to run (no profit, builds territory position).

### E4 — FACTORY (AFF + WM Minting) `[Minter]`
**File**: `token_factory.py` (50K)
**Dual mode — evaluates both paths every cycle**:
- **AFF mode**: Prices all 5 payment routes (MATH, PI, G5, Fa, Faung) → picks cheapest → `multiBuyWith(paymentToken, loops)` → sell AFF on DEX. **DISABLED** — all routes unprofitable (AFF ~50 PLS, need >118 PLS).
- **WM mode**: TGSv8 `mintWM(count)` → sell WM on DEX. Currently unprofitable (23 PLS cost vs 17 PLS DEX value).
- Both modes scan continuously for profitable gas windows.
**Critical**: `multiBuyWith()` is the ONLY path that delivers AFF to caller. `multiGenerate()` alone is useless.

### E5 — ABUPRU (LAU Mathematical State) `[Joey]`
**File**: `lau.py` (35K)
**Mechanism**: Complex mathematical state transitions on LAU token + EmitSniper.
**Gate**: 150K PLS floor. Wallet at 1.98M PLS (above floor, low priority).
**Strategic**: Always valid to run alongside other engines.

### E6 — DaVINCI (Treasury Sniper) `[Minter]`
**File**: `treasury_sniper.py` (12K)
**Mechanism**: TGSv8 `batchClaimTreasury()` on tokens with claimable backing > acquisition cost.
**Data**: `data/recon_results.json` (39K lines).
**Yield**: Realistic ~1-10K PLS after pool price impact.
**Key finding**: All high-value targets are V3 Index Minter tokens (family-isolated Claim).

### E7 — BACKBONE (Spine Runner) `[Minter]`
**File**: `spine_runner.py` (17K)
**Mechanism**: TGSv8 `batchMintAndClaim()` on Debenture=True tokens for infinite mint-claim loops.
**Data**: `data/spine_map.json`, `data/spine_opportunities.json`.
**Current**: Only OZZY has Debenture=true in V2 Federal, PLS/token near-zero (~1.54e-11).
**Blocked by**: E8 PHR3AK ARM mode — needs ammo tokens in TGSv8 to unlock.

### E8 — PHR3AK (Token Web Manipulation) `[Minter]`
**File**: `phreak.py` (47K, 1221 lines)

> *"Phantom Phreak didn't need to own the phone company. He just needed to know how the switches worked."*

**Infrastructure engine — doesn't generate PLS directly. Builds token web topology that makes other engines more profitable.**

Three modes, evaluated in priority order:

**Mode 1: ARM** (Critical path → unlocks E7 BACKBONE)
- Checks if any `deb_true_v2` token has 0 balance in TGSv8
- Finds cheapest DEX route to acquire the token (scans V1+V2 factory pairs)
- Executes via `TGSv8.swapNativeForTokens()` — tokens land in TGSv8 working balance
- Default: 100 PLS buy of OZZY → E7 has ammo for spine running
- **One TX unlocks an entire engine class.**

**Mode 2: DEPLOY** (Create new token web edges)
- Pops from `deploy_queue` in `phreak_config.json`
- `TGSv8.createV4(name, symbol, initialMint, parent)` → new V4 token
- `TGSv8.addLiquidity()` → create LP pair on V2
- Burns `(100 - keep_pct)%` of LP tokens to `0x...0369` burn address
- Removes completed deploy from queue, persists config atomically

**Mode 3: STITCH** (Create missing LP pairs between existing tokens)
- Builds token adjacency graph from `recon_results.json`
- Scores missing edges: `(connections_A × connections_B) × sqrt(min_liquidity)`
- Buys small amounts of both tokens via TGSv8 if needed
- Creates LP pair on V2, burns % of LP tokens
- Only runs when wallet >200K PLS (well above gas floor)

**Debenture Monitor** (background):
- Periodically scans all V2 Federal tokens for Debenture status changes
- Auto-discovers newly flipped `Deb=true` tokens → adds to `phreak_config.json`
- Configurable interval (default: 600s)

**Configuration** (`data/phreak_config.json`):
```json
{
  "deb_true_v2": [{"address": "...", "symbol": "OZZY", "parent": "..."}],
  "burn_address": "0x0000000000000000000000000000000000000369",
  "default_keep_pct": 20,
  "max_impact_pct": 10.0,
  "split_threshold_pct": 3.33,
  "deploy_queue": [],
  "stitch_candidates": [],
  "arm_default_pls": 100,
  "debenture_monitor_interval_s": 600
}
```

**Cross-Engine Dependencies** (Strategist V2 unlock bonuses):
```python
UNLOCK_MAP = {
    ("PHR3AK", "arm"):    ["SpineRunner"],   # ARM → E7 unlocked
    ("PHR3AK", "deploy"): ["Arb"],           # new V4 pair → new arb edge
    ("PHR3AK", "stitch"): ["Arb"],           # new LP pair → new arb edge
}
```

---

## Strategist V2

**File**: `core/strategist.py` (683 lines)

The Strategist sits between simulation and execution. It evaluates all 8 engines' `SimResult` outputs and produces a `CycleRecommendation` with up to 3 actions — one per wallet.

### Key Concepts

- **CycleRecommendation**: `{joey: Recommendation, minter: Recommendation, seller: Recommendation}` — each slot is an engine to execute or `None` (skip).
- **Rotation penalty**: Prevents engine monopolization. Engines that ran recently get score penalties.
- **Unlock bonuses**: PHR3AK ARM gets a score boost because it unlocks E7 BACKBONE (via `UNLOCK_MAP`).
- **Strategic engines**: `Beat` and `LAU` are always valid to run regardless of profit (territory + state advancement).
- **Persistent state**: `data/strategist_state.json` — cumulative P&L, per-engine history, survives restarts.

### Confidence Levels
`HIGH` → auto-execute | `MEDIUM` → execute with logging | `LOW` → execute cautiously | `SKIP` → don't run

---

## Concurrency System (V2)

**File**: `core/concurrency.py`

### SimExecutor
- `ThreadPoolExecutor` with 8 workers (one per engine)
- `parallel_simulate(engines)` → runs all eligible `sim_result()` concurrently
- 5-second timeout per engine simulation
- ~300ms total for 8 engines (vs ~2.4s sequential)

### Parallel Wallet Execution
- `execute_wallet_actions([(engine, dry_run), ...])` → `asyncio.gather()` across wallets
- Each wallet's TX pipeline is serial within itself, parallel across wallets

---

## Multi-Wallet System (V2)

**File**: `core/wallet_manager.py`

### WalletManager
- Loads 3 wallets from env vars: `DYSNOMIA_PRIVATE_KEY`, `MINTER_PRIVATE_KEY`, `SELLER_PRIVATE_KEY`
- Per-wallet `WalletNonce` tracker (fetch from chain, local increment)
- `get_wallet_for_engine(role)` — routes engine to correct wallet, falls back to Joey
- `snapshot_all_balances()` — batch PLS check across all wallets
- `check_sweep()` / `execute_sweep()` — auto-sweep excess PLS from Seller to Joey

### Sell Queue
**File**: `core/sell_queue.py`
- Scans TGSv8 for all tokens with nonzero balance via Multicall
- Estimates PLS output via `getAmountsOut` on V1 and V2 routers
- Returns sorted by `est_pls_out` descending — Seller picks the top target
- Source of truth: on-chain `balanceOf()`. JSON cache is advisory only.

---

## TGSv8 — Execution Substrate

**Address**: `0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32` (block 25,943,194)
**Source**: `contracts/TGSv8.sol`

| Function | Purpose |
|----------|---------|
| `executeRoute(Step[])` | Atomic multi-step execution (MINT→CLAIM→SWAP chain) |
| `atomicArb(...)` | Cross-DEX arbitrage in one TX |
| `batchClaimTreasury(targets[])` | Sweep backing from N treasuries |
| `batchMintAndClaim(token, count)` | N mint-claim loops in one TX |
| `mintWM(count)` | Batch WM minting |
| `createV4(name, symbol, mvAmount)` | Deploy V4 personal treasury token |
| `addLiquidity(...)` | Create/add to LP pair |
| `swapNativeForTokens(...)` | PLS → token via DEX (used by PHR3AK ARM) |
| `swapTokensForNative(...)` | Token → PLS via DEX |
| `getReservesBoth()` | V1+V2 reserves in one call |
| `deposit(token, amount)` | Deposit tokens from EOA into TGSv8 |
| `withdraw(token, amount)` / `withdrawPLS()` | Withdraw to owner |
| `bal(token)` | Check TGSv8 working balance of any token |
| `checkDebenture(token)` | Check Debenture status (used by PHR3AK monitor) |
| `setAuth(wallet, authorized)` | Authorize additional wallets (Minter/Seller) |

### Step Struct
```solidity
struct Step {
    uint8 action;    // 0=swap, 1=mint, 2=claim, 3=approve
    address target;  // Contract to call
    uint8 dex;       // 0=V1, 1=V2 (per-step DEX selection)
    bytes data;      // Encoded function call
}
```

### Current State (LIVE)
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

### Strategy B: PHR3AK ARM → BACKBONE Pipeline (E8 → E7)
**Critical path for unlocking primary revenue engine.**
1. E8 PHR3AK ARM: Buy 100 PLS of OZZY → deposits into TGSv8
2. E7 BACKBONE: Infinite mint-claim loop on OZZY (Debenture=True)
3. Sell claimed tokens via Seller wallet
- **Currently OZZY PLS/token is near-zero** — profitability depends on finding higher-value Deb=true tokens (Debenture Monitor watches for flips)

### Strategy C: Treasury Sniping (E6)
Scan treasury tokens for claimable backing > acquisition cost.
Realistic yield: ~1-10K PLS per batch after pool impact.

### Strategy D: V3 Family Exploitation (E8 DEPLOY)
High-value targets: MXDAI (118 PLS/tok, 29M liq), S&㉿500 (44K PLS/tok, 6M liq).
Requires deploying sibling tokens in same V3 family as ammo via E8 DEPLOY mode.

### Strategy E: Token Web Stitching (E8 STITCH)
Create missing LP pairs between high-connectivity tokens. New edges create new arb surfaces for E1 RAZOR.

### Strategy F: AFFECTION BuyWith Routes (E4) — DISABLED
All routes converge to ~1 pDAI/AFF. AFF must trade >118 PLS for profit. Currently ~50 PLS.

### Revenue Projections (from JOYSTICK_v2_PLAN.md)

| Target | PLS/hour | PLS/block |
|--------|----------|-----------|
| Minimum | 1,000,000 | 2,778 |
| Goal | 2,880,000 | 8,000 |

DSS at max capacity: ~184K PLS/hour. Real volume comes from treasury web engines (E6/E7/E8).

---

## Oracle System

### price.py
- `get_amounts_out(amount_in, path, router)` — DEX quote via Router
- `get_amounts_out_v2(amount_in, path)` — V2 Router specifically
- `get_reserves(pair)` — raw pair reserves

### scanner.py — 272+ QING venues discovered via MAP

### profitability.py
`amountOut = (amountIn * 997 * reserveOut) / (reserveIn * 1000 + amountIn * 997)`

### route_auditor.py — Multi-hop route profitability, AFF break-even analysis

### pair_discovery.py — Scans PulseX V1/V2, 9mm, 9inch factories. Builds `pair_registry.json`.

### graph.py — Token graph for multi-hop pathfinding. Used by E1 RAZOR and E8 STITCH.

---

## Core Modules

### config.py — Address Registry + Thresholds
All addresses as `Web3.to_checksum_address()`. Key additions in V2:
- `MULTI_AFFECTION`, `AFF_G5`, `AFF_PI`, `AFF_MATH`, `AFF_FA`, `AFF_FAUNG` — payment token addresses
- `HUB_TOKENS` — Tier 1 scan targets for pair discovery (WPLS, AFF, FED, TBILL, GIBS, FDIC, ATROPA, pDAI)
- `MINTER_WALLET`, `SELLER_WALLET` — multi-wallet addresses
- `AdaptiveDelay` — exponential backoff when idle, tighten when profitable
- Graph arb params: `GRAPH_ARB_MIN_PROFIT_PLS`, `GRAPH_ARB_MAX_IMPACT_PCT`, `GRAPH_ARB_MAX_HOPS`
- `GAS_PRICE_CEIL` — default 2M Gwei (PLS is cheap, gas is typically 500K-1M Beats)
- `BURN_ADDRESS` — `0x0000000000000000000000000000000000000369` (verified EOA, 158B PLS already burned)

### chain.py — Multicall3 batch reads, `erc20()`, `safe()`, `tgsv8_contract()`, `multi_affection_contract()`

### executor.py — `send_tx()`, `approve_if_needed()`. TX pipeline: simulate → estimate_gas → sign → submit → receipt.

### gas_guard.py — Enforces gas price ceiling + PLS minimum balance. Returns `(should_proceed, reason)`.

### rpc_provider.py — RPCPool with circuit breakers. Known bug: multi-provider `send_raw()` race condition.

### event_logger.py — JSON-L structured logging to `data/events/`.

---

## Competitive Intelligence (`data/intel/`)

### watchlist.json
Tracks competitor wallets and their AFF minting activity. Key operators:

| Tag | Address | Threat | PLS On-Hand | Last Active |
|-----|---------|--------|-------------|-------------|
| alpha_main | `0xd1bebc...` | HIGH | 600K | 2026-01-27 |
| alpha_worker_1 | `0x24db01...` | MEDIUM | 49K | 2026-01-27 |
| alpha_worker_2 | `0x9ecef9...` | LOW | 1.27M | 2026-02-15 |
| beta_worker | `0x87cf48...` | MEDIUM | 989K | 2026-01-27 |

**Alert triggers**: `multiBuyWith` spike on watched wallets signals AFF minting conditions are favorable.

---

## Key Addresses (Runtime)

| Name | Address | Role |
|------|---------|------|
| Joey Wallet | `0x17367877aF5A8D0Eb33ba5689A880f696386E24D` | EOA — identity |
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

87% of GIBS supply (3,396 total) in LP. Joey holds 0 GIBS in wallet.

---

## Running the Bot

```bash
cd scripts/Joystick
export DYSNOMIA_PRIVATE_KEY="0x..."       # Joey (required)
export MINTER_PRIVATE_KEY="0x..."          # Minter (optional — enables multi-wallet)
export SELLER_PRIVATE_KEY="0x..."          # Seller (optional — enables multi-wallet)
export TGSV8_ADDRESS="0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32"

pip install -r requirements.txt
python -m scripts.Joystick.bot                  # auto mode (3-wallet if keys set)
python -m scripts.Joystick.bot --dry-run        # simulate only, no TXs
python -m scripts.Joystick.bot --single-wallet  # force single-wallet mode
python -m scripts.Joystick.bot --interactive    # ask before each action
python -m scripts.Joystick.bot --once           # run one cycle and exit
python -m scripts.Joystick.bot --status         # print engine/strategist status
python -m scripts.Joystick.bot --wallet-status  # show 3-wallet balances + auth
python -m scripts.Joystick.bot --beat-only      # run Beat engine only
python -m scripts.Joystick.bot --lau-only       # run LAU engine only
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DYSNOMIA_PRIVATE_KEY` | — | Joey wallet key (required) |
| `MINTER_PRIVATE_KEY` | — | Minter wallet key (optional) |
| `SELLER_PRIVATE_KEY` | — | Seller wallet key (optional) |
| `MINTER_WALLET` | — | Expected Minter address (validation) |
| `SELLER_WALLET` | — | Expected Seller address (validation) |
| `TGSV8_ADDRESS` | — | TGSv8 contract address |
| `PULSECHAIN_RPC` | `rpc.pulsechain.com` | TX submit RPC |
| `PULSECHAIN_READ_RPC` | `rpc-pulsechain.g4mm4.io` | Read RPC |
| `PLS_GAS_FLOOR` | `100000` | Min PLS to keep (Joey) |
| `MINTER_GAS_FLOOR` | `30000` | Min PLS to keep (Minter) |
| `SELLER_GAS_FLOOR` | `30000` | Min PLS to keep (Seller) |
| `SWEEP_THRESHOLD` | `500000` | PLS threshold to trigger Seller→Joey sweep |
| `GAS_PRICE_CEIL` | `2000000` | Max gas price in Gwei |
| `GAS_MULT` | `1.3` | Gas estimate multiplier |
| `MAX_SLIPPAGE` | `0.02` | DEX slippage tolerance |
| `CYCLE_DELAY` | `30` | Base seconds between cycles |
| `CYCLE_DELAY_MIN` | `15` | Min adaptive delay |
| `CYCLE_DELAY_MAX` | `300` | Max adaptive delay |
| `MIN_PROFIT_PLS` | `5` | Min PLS profit to execute |
| `GRAPH_ARB_MIN_PROFIT_PLS` | `1000` | Min profit for graph arb |
| `GRAPH_ARB_MAX_HOPS` | `3` | Max hops in arb path |
| `GRAPH_CACHE_TTL` | `300` | Pair registry cache (seconds) |
| `RESERVE_CACHE_TTL` | `30` | Reserve cache (seconds) |

---

## Current State (Block 26,041,473 — 2026-03-16)

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
PLS/USD:  ~$0.0148           DSS GIBS:     0
Gas:      ~741K Beats
```

### Engine Readiness
```
E1 RAZOR:      Ready — net-negative, low priority              [Seller]
E2 CEREAL:     BLOCKED — 0 GIBS in DSS                        [Joey]
E3 MERIDIAN:   Running — Dione=41                              [Joey]
E4 FACTORY:    AFF DISABLED / WM unprofitable                  [Minter]
E5 ABUPRU:     Gated — 150K floor (wallet OK, low priority)   [Joey]
E6 DaVINCI:    Wired — needs live recon targets                [Minter]
E7 BACKBONE:   Blocked — needs E8 ARM first                    [Minter]
E8 PHR3AK:     READY — ARM mode is critical path              [Minter]
```

---

## What's Next

1. **E8 ARM** → Buy OZZY → unlock E7 BACKBONE (one 100 PLS TX)
2. **Unblock E2** — DSS needs GIBS
3. **E4 background monitoring** — scan for WM and AFF price crossover windows
4. **E6 use current recon** — treasury targets
5. **E8 STITCH** — create missing high-value LP pairs for E1 arb surfaces
6. **Debenture Monitor** — watch for V2 Federal token Deb status flips
7. **Multi-wallet deployment** — set up Minter + Seller keys, TGSv8 `setAuth()`

**Last Updated**: 2026-03-16 (block 26,041,473)
**Status**: OPERATIONAL (V2). E8 PHR3AK ready — ARM mode is critical path to unlock E7. E2 blocked (0 GIBS). AFF routes unprofitable. 3-wallet pipeline ready.
