# YUE Cascade Pump — Design

**Date:** 2026-04-25
**Author:** Joey (`|>JOYSTICK<|`) + Claude
**Status:** Approved, ready for implementation plan
**Target branch:** `claude/joystick-V2-FanxJ`
**Predecessor specs:** `2026-04-24-fdic-dfm-cycle-design.md` (Layer A), `nested-noodling-garden.md` (Layer B)

---

## Goal

Promote Joey's trillion-scale V2 Federal bag (FDIC + PARADE + DFM) from the 1× wallet tier to the 40× YUE tier so the Yuan modulus widens for every Soeng-chain read, and deepen the V2 Federal cascade with a Layer C target consuming the parked PARADE.

## Context

### Player identity (verified, in CLAUDE.md and 5+ scripts)

- **Joey EOA**: `0x17367877aF5A8D0Eb33ba5689A880f696386E24D`
- **GIBS LAU** (joey's character token): `0x66a08aa12da955eb63d7ac121a88b2b210a07b03`
- **JOEY_YUE** (joey's bank wallet): `0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0`
- **GIBS QING venue**: `0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35`

The "discover or deploy joey LAU+YUE" arc from the original draft plan is dropped — both already exist and are referenced in `recon_zuo.py`, `tx_terraform.py`, `tx_acquire_qing.py`, `beat_full_diagnostic.py`.

### Mechanical grounding (verified from source)

- **Yuan formula** (`solidity/dysnomia/domain/sky/02_choa.sol:31`):
  ```solidity
  return Bai.balanceOf(tx.origin)
       + (10 * Bai.balanceOf(address(UserToken)))
       + (40 * Bai.balanceOf(address(Yue)));
  ```
  Tokens parked in YUE count at 40×. Used by `META.Beat`, `PANG.Iota`, `ZI.Iota` — the H2O / VITUS chain. Production scripts already mirror this (`recon_zuo.py:6`).

- **YUE deposit mechanism**: plain `ERC20.transfer(JOEY_YUE, amount)`. No `Deposit` function on YUE; `CHOA.Yuan` reads `balanceOf(YUE_address)` directly (`yue.sol`).

- **YUE withdraw constraint** (`yue.sol:107`):
  ```solidity
  function Withdraw(address what, address To, uint256 amount) public onlyOwners {
      if(msg.sender != address(Chan)) revert OnlyChan(...);
      if(!hasMint(what)) revert OnlyGameTokens(what);
      ...
  }
  ```
  `Withdraw` only succeeds for game tokens (`hasMint(what) == true`) and only when called via CHAN. Non-game tokens **cannot exit YUE via Withdraw** — they can leave only via `Hong()` (swap to a QING-underlying asset that has a non-zero `GetAssetRate` for the spend token). This is a parking risk that Phase 1 must gate.

- **CHAN address**: `0xe250bf9729076B14A8399794B61C72d0F4AeFcd8` (in `recon_players.py:22`).
- **CHO address**: `0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB` (in `recon_players.py:21`).

### V2 Federal tree (partially pre-enumerated)

`scripts/Joystick/data/v2_federal_tokens.json` already lists 14 V2 Federal tokens with addresses, `selfBalance`, and `pls_per_token`. **However, its `parent_expected: "FED/BAR chain"` field is wrong for at least PARADE** (real `Parent()` on-chain is DFM, per `scripts/data/layer_b_ammo.json`). Phase 1 re-scans `Parent()` on-chain.

### Cascade state at planning time

Stage | Status | Notes
---|---|---
Layer A (FDIC→DFM) | Done | 5 ammo `幹A01..A05`, ~5,050 FDIC locked, deployed 2026-04-24 (`scripts/data/dfm_cycle_ammo.json`)
Layer B (DFM→PARADE) | Probed | 5 ammo `幹B01..B05`, ~50 DFM locked, 1 cycle at N=10 verified (`scripts/data/layer_b_ammo.json`)
Layer C (PARADE→?) | Not started | Target unselected. Phase 4 of this plan.

### Holdings reference (from plan author's recon, 2026-04-25)

Token | EOA balance | Notes
---|---|---
PLS | ~1,054,842 | 10× the 100K floor
WPLS | 348,400 | Gas/swap utility
AFFECTION | 2,720 | Untouched
FDIC | ~66 T | Layer A output (cumulative)
PARADE | ~96.79 T | Layer B output + Maria's pre-existing balance
DFM | ~5.95 B | Layer A output

These are accepted from the plan draft but **must be re-read at execution time, not at planning time**. Phase 1 re-reads as a side effect.

---

## Architecture

Five sequential phases. Each lands as one or more commits on `claude/joystick-V2-FanxJ`. Phases 2 and 3 can run in parallel after Phase 1 completes; Phase 5 depends on Phase 4 which depends on Phase 1c.

```
Phase 1 (Discovery) ──┬──> Phase 2 (YUE parking) ──┐
                      │                            ├──> ready
                      ├──> Phase 3 (Layer B scale) ┘
                      │
                      └──> Phase 4 (target select) ──> Phase 5 (Layer C deploy + cycle)
```

### Files created by this plan

- `docs/superpowers/specs/2026-04-25-yue-cascade-pump-design.md` (this file)
- `docs/superpowers/plans/2026-04-25-yue-cascade-pump.md` (writing-plans output)
- `scripts/data/maria_v2federal_tree.json` (Phase 1c output)
- `scripts/data/yue_park_state.json` (Phase 2 runtime state)
- `scripts/data/target_choice.json` (Phase 4 output)
- `scripts/data/layer_c_ammo.json` (Phase 5 runtime state)
- `scripts/tx_yue_park.py` (Phase 2 script)
- `scripts/tx_layer_c_cycle.py` (Phase 5 script — mirror of `tx_layer_b_cycle.py`)

### Files reused

- `scripts/tx_layer_b_cycle.py` (Phase 3 driver, no edits — only a wrapper loop)
- `scripts/Joystick/data/v2_federal_tokens.json` (Phase 1c input)

---

## Phase 1 — Pre-flight discovery

**Goal:** Resolve all unknowns and gates with read-only on-chain calls before any state-changing TX.

### 1a — Yuan / 40× sanity read
For one of `{FDIC, DFM, PARADE}`:
- Read `balanceOf` on each of `{joey EOA, GIBS_LAU, JOEY_YUE}`.
- Read `CHOA.Yuan(token)` from joey's `tx.origin`.
- Assert `Yuan == bal(EOA) + 10×bal(LAU) + 40×bal(YUE)` to the wei.

If the assertion fails, the entire plan's premise is broken — abort and investigate before proceeding.

### 1b — YUE exit-mechanism check (the parking gate)

For each `token ∈ {FDIC, PARADE, DFM}`:
- `YUE.hasMint(token)` on `JOEY_YUE` → boolean A. (True ⇒ Withdraw is theoretically callable.)
- For each known QING in `data/contracts.json` (or via CHOA enumeration), call `QING.GetAssetRate(QING_underlying, token)`. If any QING returns a non-zero rate with `token` as SpendAsset, exit-via-Hong is possible → boolean B.
- Decision rule per token:
  - If A is true OR B is true → **exit path exists**, park aggressively per Phase 2 table.
  - If both false → **one-way deposit risk**, park ≤10% of bag (treat as quasi-permanent Yuan deposit).

Output: `data/yue_exit_check.json` documenting per-token A/B booleans and the parking cap.

### 1c — V2 Federal tree re-scan
For each token in `scripts/Joystick/data/v2_federal_tokens.json`:
- On-chain reads: `Parent()`, `Debenture()`, `totalSupply()`, `decimals()`.
- Build `children` array by scanning `V2Minter` `New(string,string,uint256,address)` events from the contract's deployment block to `latest`, joining where the event's `parent` argument matches this token.
- Tag each token with `deployer` (from `V2Minter.TreasuryTokens(token)`).

Output: `scripts/data/maria_v2federal_tree.json` with corrected parents and full children listing. This is Phase 4's input.

### 1d — Joey's FED balance + holdings refresh
Read `balanceOf(joey)` for `{FED, FDIC, DFM, PARADE, WM, WPLS, AFFECTION, PLS}`. Persist to `data/yue_park_state.json` as the authoritative pre-parking baseline. If FED > 0, FED-children become candidates in Phase 4.

**Phase 1 produces zero state-changing TX. All four sub-phases can run in parallel.**

---

## Phase 2 — YUE parking

### Mechanism
Plain `ERC20.transfer(JOEY_YUE, amount)` per chunk. No approval needed (sender is the EOA, transferring its own balance).

### Sizing (subject to Phase 1b verdict)

Token | EOA reserve (kept) | YUE-park target | Comment
---|---|---|---
DFM | 600 M | 5.35 B | 100 Phase-3 cycles need 500.05 M (5N+5K @ N=1M, K=100); 600 M leaves a 100 M cushion
FDIC | 50 B | 65.95 T | ≈1,000 Layer-A cycles @ N=10M, K=100 (cycle cost 50,000,500 FDIC), plus discretionary
PARADE | 1 T | 95.79 T | ≈200,000 Phase-5 cycles @ N=1M, K=100 (cycle cost 5,000,500 PARADE), plus sale optionality
WPLS / AFFECTION | keep all | 0 | Not Yuan-relevant for current QINGs

If Phase 1b says any token has no exit path, that token's park target is capped at 10% of bag (the entire EOA-reserve column scales accordingly).

### Script: `scripts/tx_yue_park.py`

CLI:
```
python3 scripts/tx_yue_park.py --token {FDIC,PARADE,DFM} --amount <wei> [flags]

--chunks <int>   Split the amount into N transfers (default 4)
--dry-run        eth_call simulate every transfer, submit none
--yes            Skip per-chunk interactive confirmation
--verify         Print balances + Yuan reads, exit
```

### Per-chunk safety
1. Pre-chunk: read `balanceOf(joey, token)`, `balanceOf(JOEY_YUE, token)`, `CHOA.Yuan(token)`.
2. Submit `transfer(JOEY_YUE, chunk_wei)`.
3. Post-chunk: re-read all three. Assert:
   - `Δ balanceOf(joey)  == -chunk_wei`
   - `Δ balanceOf(YUE)   == +chunk_wei`
   - `Δ Yuan             == +40 × chunk_wei`
4. Any mismatch aborts the run, dumps state to `data/yue_park_state.json`.

### Sentinel pass before scale
First chunk per token = 1% of intended park amount, with full assertion battery. Only continue parking if assertions pass.

### Watchdog
At every chunk: re-read `WITHOUT.balanceOf(joey)`. Nonzero ⇒ abort and surface (manual response — not part of this plan's scope to dump-to-dead).

---

## Phase 3 — Layer B production scaling

**Driver:** existing `scripts/tx_layer_b_cycle.py --phase cycle --n 1000000 --hold-back 100` in a wrapper loop.

### Wrapper script

A new minimal script `scripts/tx_layer_b_loop.py` (or shell wrapper) that:
1. Reads pre-cycle balances: `(joey_DFM, joey_PARADE, vault_DFM_per_ammo, joey_ammo_per_ammo)`.
2. Invokes `tx_layer_b_cycle.py --phase cycle --n 1000000 --hold-back 100 --yes`.
3. Reads post-cycle balances; asserts:
   - `ΔDFM_joey  == -(5N + 5K)` where N=1,000,000 and K=100
   - `ΔPARADE_joey == +5N`
   - `Δvault_DFM[i] == +N` for each ammo i
   - `Δjoey_ammo[i] == +K` for each ammo i
4. On any assertion failure: halt, surface the discrepancy, **do not auto-retry**.
5. On success: increment cycle counter, sleep briefly, repeat until counter = 100 (configurable).

### Budget
- Cycles: 100 × N=1M, K=100
- DFM consumed: 100 × 5,000,500 = 500.05 M (within the 600 M Phase-2 reserve)
- PARADE produced: 100 × 5,000,000 = 500 M (fuels Phase 5)
- 幹B inventory built per token: 100 × 100 = 10,000
- Gas: ~0.5 PLS/cycle × 100 = 50 PLS (joey has 1.05 M)
- Wall time: ~3.5 hours (11 TX/cycle, ~10 sec block time, plus verify)

### Run posture
tmux/screen session — do not background-fork from a one-off shell call. Phase 3 can run in parallel with Phase 2 chunks (they touch disjoint balances).

---

## Phase 4 — Layer C target selection

**Goal:** Pick the highest-value V2 Federal target whose Parent we can fuel.

### Inputs
- `scripts/data/maria_v2federal_tree.json` (Phase 1c)
- `data/yue_park_state.json` (Phase 1d, for FED-balance check)
- CHOA QING enumeration for the QING-underlying check (existing `recon_*.py` may already cover this — investigate during execution)

### Ranking (lexicographic)

For each Maria-deployed V2 Federal token (or self-deploy fallback):

1. **Parent reachable.** Parent ∈ `{DFM, FDIC, PARADE}` (always reachable) or Parent == FED and joey's FED balance > 0. Targets failing this drop out.
2. **Has children.** Count of V2Minter-deployed tokens whose `Parent` points back to this one. Higher = better (stepping stone to Layer D).
3. **Is QING underlying.** Boolean. True = closed-loop H2O benefit when we park it.
4. **Smallest `totalSupply()`** as tie-break (cheapest to dominate the float of).

### Output

`scripts/data/target_choice.json`:

```json
{
  "winner": {
    "address": "0x…",
    "symbol": "…",
    "parent": "0x…",
    "parent_symbol": "…",
    "score": { "parent_reachable": true, "child_count": 2, "is_qing_underlying": false, "total_supply": "…" }
  },
  "runner_up": { "...same shape — for future Layer D..." },
  "all_candidates": [ { "..." } ]
}
```

### Fallback
If no Maria token meets criterion 1, fall back to self-deploying the target via `V2Minter.New("…", "…", initialMint, PARADE)`. PARADE-parented self-targets are abundantly fuelable from the 1 T PARADE reserve. Document the choice in `target_choice.json` with `"self_deployed": true`. **Cost:** `initialMint` WM is pulled from joey at deploy. Verify `WM.balanceOf(joey) ≥ initialMint` before invoking; CLAUDE.md state shows joey ≈ 263 WM, so `initialMint` is bounded — pick a small starting supply (e.g. 1 WM) since Yuan-tier benefit is from balance held, not from float dominance.

**Phase 4 produces zero state-changing TX.**

---

## Phase 5 — Layer C deploy + first cycle

### Script: `scripts/tx_layer_c_cycle.py`

Structurally identical to `scripts/tx_layer_b_cycle.py`. Same phase set:

| Phase | Purpose | TXs |
|---|---|---|
| `approve` | `WM→V2Minter` (if not MAX), `<TARGET_PARENT>→TARGET` | 1–2 |
| `deploy` | 5× ammo `New` (Parent = TARGET_PARENT), 5× `<TARGET_PARENT>→ammo`, 5× `ammo→TARGET` | 15 |
| `probe` | `TARGET.mint(1)` + `TARGET.Claim(幹C01, 1)` | 2 |
| `cycle --n N --hold-back K` | `TARGET.mint(5N) + 5×ammo.mint(N) + 5×Claim(N-K)` | 11 |

### Ammo parent rationale

Both `TARGET.mint()` and `ammo.mint()` consume `TARGET_PARENT` (because ammo's `Parent == TARGET.Parent`). One `Claim(N-K)` returns `(N-K) × TARGET_PARENT` to joey. Net per cycle: `5N + 5K` TARGET_PARENT consumed; `5N` TARGET produced; `K` of each ammo retained.

This mirrors Layer B exactly — only the token addresses differ.

### State file: `scripts/data/layer_c_ammo.json`

Same shape as `layer_b_ammo.json`: `target` block, `probe_verified` boolean, `ammo[]` array of 5 entries with address/deploy_tx/debenture_verified/parent.

### First cycle
- N=1M, K=100
- Run via the same wrapper-loop pattern as Phase 3 with full inter-cycle invariant assertions
- First 10 cycles slow with verification; ramp loop speed only after invariants stabilise

### Stop conditions
- Target's `maxSupply` reached (some V2 Federal tokens may have caps)
- Discovery that the chosen target was a poor pick (e.g., probe phase reveals an unexpected admin-only Claim) — switch to runner-up. **Caveat:** if the runner-up's Parent differs from the winner's Parent, the deployed `幹C` ammo are unusable for it (ammo's `Parent` is fixed at deploy). A parent-mismatched runner-up requires deploying a new `幹D` ammo set with `Parent = runner_up.Parent`. Plan accordingly.
- Per-block / per-tx rate limit on V2Minter (not currently expected, but possible)

---

## Safety rails (cross-phase, non-negotiable)

1. **Gas floor**: `PLS_balance(joey) > 100,000 × 10^18` before any submit. Skip if violated.
2. **Gas price ceiling**: `eth_gasPrice < GAS_PRICE_CEIL` before any submit.
3. **EIP-1559 Type 2 only**: `maxFeePerGas` + `maxPriorityFeePerGas`. Priority tip ≥ 100,000 Beats (per memory `feedback_pulsechain_priority_fee.md`).
4. **`estimate_gas` × 2.5 multiplier** (per memory `feedback_gas_eip1559.md`); abort if estimate reverts.
5. **`eth_call` simulation must succeed** for every submitted TX.
6. **Single `Web3.HTTPProvider(SUBMIT_RPC)`** for submit — avoids RPCPool race.
7. **Chain ID 369** set explicitly on every TX.
8. **Interactive confirmation per phase** unless `--yes`.
9. **WITHOUT watchdog**: every chunk in Phase 2 and every cycle in Phase 3/5 re-reads `WITHOUT.balanceOf(joey)`. Nonzero halts the script.
10. **Atomic state writes** via `os.replace()` for every JSON file touched.

---

## Out of scope (deferred to follow-on plans)

- **Phase 6 (steady-state compound loop)** — depends on the `d-compound` skill which is not loaded in this Claude Code session. Becomes its own plan once the skill content is available.
- **CROWS accumulation toward 25e18 / E9 CROWN**.
- **Layer D deploy** — runner-up from Phase 4. Requires Layer C to demonstrate ≥100 stable cycles first.
- **QING-utility audit across all V2 Federal tokens** — broader than this plan.
- **TGSv8 atomic routing** to wrap full cycle batches in a single TX.
- **Concurrent TX submission** (nonce-parallel optimization) — sequential is fine for POC.
- **Joystick-bot strategist integration** — Phase 5 is intentionally a standalone `tx_*.py` per project's prototyping convention.

---

## Success criteria

This plan completes its first iteration successfully when **all** of the following hold:

1. `data/yue_exit_check.json` exists and the parking decision rule from Phase 1b was applied.
2. ≥90% of joey's FDIC, ≥95% of joey's PARADE, ≥90% of joey's DFM is parked in `JOEY_YUE` **OR** capped per the Phase 1b decision rule (whichever is smaller).
3. `CHOA.Yuan(token)` for each parked token returns the expected 40×-weighted value (assertion passes at the final chunk of each parking run).
4. Phase 3 wrapper loop completes ≥100 production cycles with zero invariant failures.
5. Phase 5 `tx_layer_c_cycle.py` is deployed, the probe TX pair succeeds, and ≥10 production cycles run with zero invariant failures.

### What this plan does NOT directly produce
- PLS-denominated profit. The Yuan widening unlocks larger H2O / VITUS mints in the Soeng chain, which may convert to PLS via DEX, but the conversion path is unmeasured by this plan and belongs in the Phase 6 follow-on. Validator-fund P&L (per memory `feedback_arb_trigger_design.md`) is the project-level KPI, but this plan is a Yuan-tier preparation step, not a direct PLS pump.

---

## RPC strategy

Per `scripts/CLAUDE.md`:
- `READ_RPC = https://rpc-pulsechain.g4mm4.io` — reads, `eth_call`, `estimate_gas`
- `SUBMIT_RPC = https://rpc.pulsechain.com` — TX submission only

Wallet key via `JOEY_PK` env var. No hardcoding.

---

## Persistence across sessions

After Phase 4 + 5 land:
- Memory entry `project_layer_c_cycle.md` — Layer C ammo addresses, target address, deploy block, script path, first-cycle verification.
- Memory entry `project_yue_parked_balances.md` — final parked balances per token, exit-mechanism verdict per token.

These let future sessions resume at `--phase cycle` for Layer C and skip re-parking.

---

## References

- Yuan formula source: `solidity/dysnomia/domain/sky/02_choa.sol:28-31`
- YUE source: `solidity/dysnomia/domain/yue.sol`
- CHAN source: `solidity/dysnomia/domain/sky/01_chan.sol`
- Layer A spec: `docs/superpowers/specs/2026-04-24-fdic-dfm-cycle-design.md`
- Layer A script: `scripts/tx_dfm_cycle.py`
- Layer B script: `scripts/tx_layer_b_cycle.py`
- Layer B state: `scripts/data/layer_b_ammo.json`
- V2 Federal token cache (input to Phase 1c): `scripts/Joystick/data/v2_federal_tokens.json`
- Script conventions: `scripts/CLAUDE.md`
- Project context: `CLAUDE.md` Parts 1 (Yuan, V2 Federal) and 2 (Joey identity, JoystickHub)
- Memory: `feedback_pulsechain_priority_fee.md`, `feedback_gas_eip1559.md`, `feedback_arb_trigger_design.md`
