# FDIC → DFM Treasury Cycle — Design

**Date:** 2026-04-24
**Author:** Joey (`|>JOYSTICK<|`) + Claude
**Status:** Approved, ready for implementation plan
**Target branch:** `claude/joystick-V2-FanxJ`

---

## Goal

Convert Joey's 66T FDIC holdings into DFM via a V2 Federal mint-claim cycle using 5 self-deployed ammo tokens. Proof-of-concept first (small N), then scale.

## Context

Joey holds **66,000,000,000,165 FDIC** (block 26,369,210). Existing E7 spine_runner is wired but blocked — only OZZY has Debenture=true among known V2 Federal tokens, and OZZY has near-zero PLS/token value. This cycle creates fresh Debenture=true ammo specifically for the FDIC→DFM conversion.

### Mechanical grounding (verified from `solidity/federalminter.sol`)

- `TT.mint(amt)` — `Parent.transferFrom(caller, this, amt)` + `_mint(caller, amt)`. No Debenture check. No 2x bug.
- `TT.Claim(ammo, amt)` — owner-registered ammo requires `ammo.Debenture() == true`. Transfers ammo from caller to `this`, transfers `this.Parent` back to caller.
- `V2Minter.New(name, symbol, initialMint, parent)` — pulls `initialMint` WM from caller, deploys new TT with `Debenture=true`, registers `TreasuryTokens[newToken] = tx.origin`, mints `initialMint` of new token to tx.origin.

### On-chain state verified

- Joey FDIC: 66,000,000,000,165 ✓
- Joey WM: 20,063 (need 5 for deployments) ✓
- Joey PLS: 239,659 (above 100K floor) ✓
- FDIC.Parent = FED ✓
- DFM.Parent = FDIC ✓
- DFM vault FDIC balance: 0 (each batch seeds its own)
- FDIC owner in V2Minter: `0xBF1829…` (registered — required for ammo deployment)

### Economics per batch (N tokens per round, 5 rounds = 1 batch)

- 10N FDIC approvals needed (transient)
- 5N FDIC permanently locked across 5 ammo vaults
- 5N DFM gained
- Gas: ~22 PLS per 11-TX batch

At DEX prices, FDIC (1.26e-8 PLS) > DFM (3.82e-10 PLS) — this is not a PLS-generation strategy. Rationale is FDIC → DFM accumulation for downstream use.

---

## Architecture

**Single standalone script:** `scripts/tx_dfm_cycle.py`, following the `scripts/tx_*.py` pattern from `scripts/CLAUDE.md`. Not integrated with the Joystick bot — prototyping ground, per project convention.

### Phase structure

Three phases invoked via `--phase`:

| Phase | Purpose | TXs | Idempotent |
|-------|---------|-----|------------|
| `approve` | Static approvals that don't need ammo addresses | 2 | Yes — skip if allowance already MAX |
| `deploy` | Deploy 5 ammo tokens + interleaved approvals | 15 | Yes — skip if state file has 5 valid ammo |
| `cycle --n N` | Execute one batch (mint DFM, mint ammo × 5, claim DFM × 5) | 11 | No — consumes 5N FDIC per run |

### CLI surface

```
python3 scripts/tx_dfm_cycle.py --phase {approve,deploy,cycle} [flags]

--n <int>         Tokens per round (cycle phase only). Default: 10.
--dry-run         eth_call simulate every TX, submit none.
--yes             Skip per-TX interactive confirmation.
--verify          Print balances + approvals + ammo state, exit.
```

### State file

`scripts/data/dfm_cycle_ammo.json` — persisted atomically via `os.replace()`:

```json
{
  "deployed_at_block": 26369210,
  "ammo": [
    {
      "symbol": "幹A01",
      "address": "0x…",
      "deploy_tx": "0x…",
      "debenture_verified": true,
      "parent": "0x812571A12330A74E2A3C1fF8953f6f3aac7a83e9"
    },
    …
  ]
}
```

---

## Phase details

### Phase `approve`

Two TXs, both MAX approvals:
1. `WM.approve(V2Minter, uint256.max)` — funds future ammo deployments
2. `FDIC.approve(DFM, uint256.max)` — lets `DFM.mint()` pull FDIC

Check `allowance()` first for each pair; skip the TX if already MAX.

### Phase `deploy`

For each of 5 ammo (`幹A01` through `幹A05`):
1. **Pre-simulate** via `eth_call` on `V2Minter.New("幹 A0X", "幹A0X", 1 * 10**18, FDIC)` — returns the deterministic CREATE address that the real TX will produce
2. Submit real TX; after receipt confirms, verify the predicted address has deployed code (`eth_getCode != 0x`)
3. Verify on-chain state at that address: `ammo.Debenture() == true`, `ammo.Parent() == FDIC`, `V2Minter.TreasuryTokens(ammo) == Joey`
4. `FDIC.approve(ammo, uint256.max)` — lets `ammo.mint()` pull FDIC
5. `ammo.approve(DFM, uint256.max)` — lets `DFM.Claim(ammo, …)` pull ammo
6. Append to `dfm_cycle_ammo.json` atomically

Total: 5 deploys + 10 approvals = 15 TXs.

### Phase `cycle --n N`

One batch = 11 sequential TXs from Joey wallet:

```
TX  1:  DFM.mint(5N × 10^18)              — seeds DFM vault with 5N FDIC, mints 5N DFM to Joey
TXs 2-6:  幹A0X.mint(N × 10^18) × 5       — locks N FDIC in each 幹A0X vault, mints N 幹A0X to Joey
TXs 7-11: DFM.Claim(幹A0X, N × 10^18) × 5 — burns N 幹A0X per call into DFM's vault, receives N FDIC per call
```

**Sequential, not concurrent.** The theoretical ordering allows parallel submission (TXs 2-6 can overlap TX 1, TXs 7-11 can overlap each other after TX 1 confirms), but for a POC the ~22 PLS gas savings aren't worth the nonce-management complexity.

**Post-batch verification (in-script):**
- `ΔDFM_wallet == +5N × 10^18`
- `ΔFDIC_wallet == -5N × 10^18`
- Each ammo's FDIC balance increased by `N × 10^18`

---

## Safety rails

Non-negotiable checks before any submit:

1. `PLS_balance(Joey) > 100_000 × 10^18` — gas floor from CLAUDE.md
2. For cycle phase: `FDIC_balance(Joey) ≥ 10N × 10^18` — transient need
3. `eth_gasPrice < GAS_PRICE_CEIL` — skip cycle if too high
4. `eth_call` simulation must succeed for every TX
5. `estimate_gas()` × 2.5 multiplier; abort if estimate reverts
6. EIP-1559 Type 2: `maxFeePerGas`, `maxPriorityFeePerGas = 1_000_000` Beats
7. Single `Web3.HTTPProvider(SUBMIT_RPC)` for submit — avoids RPCPool race
8. Interactive confirmation per-phase unless `--yes`
9. Chain ID 369 set explicitly

Any revert aborts the active phase. Partial state is always recoverable (approvals and deploys are idempotent; a partially-failed cycle leaves excess FDIC approval and excess ammo balance in Joey's wallet, which a subsequent cycle can consume).

---

## RPC strategy

Per `scripts/CLAUDE.md`:
- `READ_RPC = https://rpc-pulsechain.g4mm4.io` — reads, `eth_call`, `estimate_gas`
- `SUBMIT_RPC = https://rpc.pulsechain.com` — TX submission only

Wallet key via `JOEY_PK` env var. No hardcoding.

---

## Test sequence

| # | `--phase` | `--n` | Flags | Purpose |
|---|-----------|-------|-------|---------|
| 1 | approve | — | `--dry-run` | Simulate static approvals |
| 2 | approve | — | — | Submit 2 approvals |
| 3 | deploy | — | `--dry-run` | Simulate 15 TXs (deploys + approvals) |
| 4 | deploy | — | — | Deploy 5 ammo, persist addresses |
| 5 | cycle | 10 | `--dry-run` | Simulate 11-TX batch at N=10 |
| 6 | cycle | 10 | — | **POC:** +50 DFM gained, 50 FDIC locked across ammo |
| 7 | cycle | 1000 | `--dry-run` | Simulate at scale |
| 8 | cycle | 1000 | — | Production run: +5,000 DFM, 5,000 FDIC locked |

After run #8 succeeds, the script can be called repeatedly at any N to continue converting FDIC → DFM.

---

## Persistence across sessions

Once `--phase deploy` completes, a memory entry (`project_dfm_cycle_ammo.md`) will be written with the 5 ammo addresses, `deploy_tx` hashes, and state-file path, so future sessions can resume at `--phase cycle` without re-running discovery.

---

## Out of scope (for this spec)

- Integration with Joystick bot's strategist / engine ranking
- TGSv8 atomic routing (`executeRoute` wrapping the full batch)
- Concurrent TX submission (nonce-parallel optimization)
- Automated scale-up / loop-until-depleted driver
- DFM downstream use (what we do with accumulated DFM)

These are separate design discussions post-POC.

---

## References

- V2 Federal Minter source: `solidity/federalminter.sol`
- Existing spine runner: `scripts/Joystick/engines/spine_runner.py`
- V2 Federal token cache: `scripts/Joystick/data/v2_federal_tokens.json`
- Script conventions: `scripts/CLAUDE.md`
- Project context: `CLAUDE.md` Part 1 (Federal Minter system, Purchase/Claim mechanics)
