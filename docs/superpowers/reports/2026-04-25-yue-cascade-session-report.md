# YUE Cascade Pump — Session Report

**Date:** 2026-04-25
**Branch:** `claude/joystick-V2-FanxJ`
**Author:** Joey (`|>JOYSTICK<|`) + Claude Opus 4.7 (1M context)
**Spec:** `docs/superpowers/specs/2026-04-25-yue-cascade-pump-design.md`
**Plan:** `docs/superpowers/plans/2026-04-25-yue-cascade-pump.md`
**Commits:** 21 (commit range `ebda118..c03d8da`)

---

## TL;DR

The plan as originally drafted was based on a false premise about which tokens enter the Yuan reward formula. We caught and verified the error before parking any tokens (saving the bag from being permanently locked in YUE), then executed the parts of the plan that actually create value:

- ✅ **Layer C cascade is live.** New target = TLRz (parent=PARADE), 5 ammo `幹C01-C05` deployed, 10 production cycles at N=1M K=100 completed.
- ✅ **+50,000,000 TLRz** accumulated (joey now holds 51,225,335,076,313 TLRz, up from 51,225,285,076,313).
- ✅ **+1,000 of each 幹C ammo** accumulated for future upstream conversion.
- ❌ **Phase 2 parking dropped** after on-chain verification proved Yuan(FDIC/PARADE/DFM) is never read by the H2O reward chain.
- ⏸ **Task 11 (Layer B 100 cycles) deferred** — pending operator decision to mirror gas-param patches before launch.

---

## Original plan premise vs. on-chain reality

The handed-off plan claimed:

> "Convert joey's enormous EOA-tier bag (66 T FDIC + 96.79 T PARADE + 5.95 B DFM, all currently sitting at the 1× Yuan tier) into a 40×-tier YUE position … widening the modulus of the entire Charge → ZI.Iota → PANG.Iota chain."

The Yuan formula source confirmed: `CHOA.Yuan(token)` returns `bal(EOA) + 10×bal(LAU) + 40×bal(YUE)`. **But the formula is only ever called by the reward chain with two argument types:**

1. `Yuan(QingAddress)` — in `META.Beat` (line 31), `PANG.Iota` (lines 29-30): reads the QING venue token's balance.
2. `Yuan(Tethys)` — in `ZI.Iota` (lines 34-35), where `Tethys = CHO contract`.

`Yuan(FDIC)`, `Yuan(PARADE)`, and `Yuan(DFM)` are **never invoked by the H2O reward chain**. The 40× YUE-tier weighting on those tokens would be applied to a number that is never read.

Worse, parking those tokens would have permanently locked them: Phase 1b confirmed `YUE.hasMint(token) = false` for all three, AND no QING returned a non-zero `GetAssetRate` for them, meaning the only exit paths (`Withdraw` or `Hong`) were both closed.

The plan author conflated "token has YUE balance" with "Yuan formula widens for that token." The correct mental model is: parking widens Yuan ONLY for tokens that the reward chain reads via Yuan() — i.e., the QING joey is computing Beat for (currently GIBS_QING, where joey holds 0) and CHO (where joey holds 0.003 at LAU only).

**Memory entry preserving this finding:** `~/.claude/projects/-opt-joystick-repo/memory/project_yuan_formula_callers.md`.

This means a future "Beat-Yuan acquisition plan" — acquiring GIBS_QING and CHO tokens, then parking them in YUE — is the actual H2O reward unlock. That work is queued as a separate brainstorming target.

---

## What was built (code + docs)

### Documentation
| File | Purpose |
|---|---|
| `docs/superpowers/specs/2026-04-25-yue-cascade-pump-design.md` | Design spec. 5 phases, mechanical grounding, safety rails, success criteria. |
| `docs/superpowers/plans/2026-04-25-yue-cascade-pump.md` | Implementation plan. 16 numbered tasks, exact file paths and code blocks. |
| `docs/superpowers/reports/2026-04-25-yue-cascade-session-report.md` | This document. |

### Scripts created
| File | Purpose | Status |
|---|---|---|
| `scripts/recon_yue_cascade.py` | Phase 1 read-only discovery. Four `--check` sub-commands: yuan, exits, tree, holdings. | Built + run live (Phase 1 complete). |
| `scripts/tx_yue_park.py` | Phase 2 chunked YUE deposits with 40× delta assertions. Hardened safety gate via `--verify`. | Built; **never executed live** (Phase 2 dropped per the Yuan finding). |
| `scripts/tx_layer_b_loop.py` | Phase 3 wrapper around existing tx_layer_b_cycle.py with hard inter-cycle invariant assertions. | Built; **never executed live** (Task 11 deferred). |
| `scripts/select_layer_c_target.py` | Phase 4 ranker. Reads tree+holdings, ranks by parent reachability + child count + supply. | Built + run; produced FDIC as winner (smallest supply); user override to TLRz for fuel runway. |
| `scripts/tx_layer_c_cycle.py` | Phase 5 cycle: PARADE → TLRz mint-claim batch via 5 自deployed 幹C ammo. Mirror of tx_layer_b_cycle.py with edits. | Built + run live (10 cycles complete). |

### Runtime state files produced
| File | Lines | What it captures |
|---|---|---|
| `scripts/data/yue_exit_check.json` | ~30 | Per-token YUE exit verdict. All 3 parking tokens flagged ONE-WAY. |
| `scripts/data/maria_v2federal_tree.json` | ~250 | 14 V2 Federal tokens with corrected Parent() + children. Reveals linear spine. |
| `scripts/data/yue_park_state.json` | ~30 | Joey's pre-parking baseline balances. |
| `scripts/data/target_choice.json` | ~200 | Layer C ranker output + manual override to TLRz. |
| `scripts/data/layer_c_ammo.json` | 47 | 5 ammo addresses, deploy block 26378961, probe verified. |

---

## What was executed on-chain

### Phase 1 (Discovery) — complete
- Yuan formula sanity confirmed: matches source for all three V2 Federal tokens.
- Exit-mechanism check: FDIC, PARADE, DFM all flagged ONE-WAY (cap 10%) due to no `hasMint` and no QING with non-zero `GetAssetRate`.
- V2 Federal tree re-scan: 14 tokens enumerated with on-chain `Parent()`. **Discovery: Maria's tree is a pure linear spine** (FDIC → DFM → PARADE → TLRz → JOB → SSA → SCOIETY → CAMPAIGN → OPIUM → BGDHTZ → TEHATER → ARMS → BAR → OZZY). Every node has exactly 1 child except OZZY (leaf).
- Holdings refresh: confirmed FDIC=66T, PARADE=96.79T, DFM=5.95B, **FED=154,683** (an open question from spec — joey does hold FED, making FED-children Phase 4 candidates), WM=20K, PLS=1.05M, WITHOUT clean.

### Phase 2 (Parking) — DROPPED
After verifying the Yuan formula isn't read for FDIC/PARADE/DFM, parking would have locked the bag indefinitely with zero reward benefit. Tasks 8 and 9 deleted from the queue. Code is built and tested but unused — kept on-branch for the Beat-Yuan acquisition plan that will reuse the same chunked-transfer + assertion-battery pattern for GIBS_QING and CHO.

### Phase 4 (Target selection)
- Ranker selected FDIC (smallest reachable supply at 2.98×10¹⁷).
- User override to **TLRz** for operational reasons: PARADE provides 96.79T fuel runway vs FED's 154K. Saved as `manual_override` field in `target_choice.json`.

### Phase 5 (Layer C deploy + cycles) — complete

**Approve phase (1 TX, ~0.06 PLS):**
- PARADE → TLRz allowance set to MAX (`0x6164b71a...`)

**Deploy phase (15 TX, ~16 PLS, 5 WM consumed):**
| Ammo | Address | Deploy TX |
|---|---|---|
| 幹C01 | `0xA3FAbf8C7Bf13E4E7499a16E77157312E565cdEE` | `0x8436bd54...` |
| 幹C02 | `0x043E0D2bFB32fD5dCaC1895FB03287fE08eFD9a9` | `0x38e7def0...` |
| 幹C03 | `0xeCDa1083d0A046925D8585EA5f4A2F75b32fCA1c` | `0x7ac97d26...` |
| 幹C04 | `0x7A33a683CaB37880b2F4C15A1630178785b61ccD` | `0xd01b60a9...` |
| 幹C05 | `0x05b193143AB63ff27E58A1FbD026CC54986A2AF1` | `0x1b7cbfce...` |

All verified Debenture=true, Parent=PARADE, Owner=Joey.

**Probe phase (2 TX, ~0.2 PLS):**
- TLRz.mint(1) + TLRz.Claim(幹C01, 1) — deltas exact (+1 TLRz, 0 ΔPARADE, -1 幹C01). Probe-verified flag set.

**Production cycles (10 cycles × 11 TX = 110 TX nominal, ~135 TX actual due to recoveries, ~70 PLS gas):**

| Cycle | Status | Notes |
|---|---|---|
| 1 | ✅ clean | Block 26379087 |
| 2 | ⚠️ partial → recovered | TX timed out at 420s (confirmed at ~7 min). 6 missing TX submitted via `/tmp/recover_cycle2.py`. |
| 3 | ✅ clean | After receipt timeout patched to 1200s |
| 4 | ✅ clean | |
| 5 | ✅ clean | |
| 6 | ✅ clean | |
| 7 | ⚠️ partial → recovered | TX **dropped** (NOT FOUND in mempool) at fee-spike. Recovery via `/tmp/recover_cycle7.py` with bumped priority fee 200K Beats + 3× max-fee multiplier. |
| 8 | ✅ clean | After gas-param patches landed |
| 9 | ✅ clean | |
| 10 | ✅ clean | |

**Final state delta over 10 cycles:**
- Joey TLRz: **+50,000,000** (5N × 10)
- Joey PARADE: **−50,005,000** (5N+5K × 10)
- Each Joey 幹C ammo: **+1,000** (K=100 × 10)
- Each 幹C vault: **+10,000,000 PARADE locked**

All invariants held to-the-wei across all 10 cycles.

---

## Key learnings worth keeping

### 1. Yuan formula has narrow callers (saved as memory entry)
The reward chain calls `CHOA.Yuan(token)` with only QING addresses and CHO. Future plans aiming at Yuan widening must target these tokens specifically — V2 Federal treasury tokens are spectators to the reward formula. See `memory/project_yuan_formula_callers.md`.

### 2. Maria's V2 Federal universe is a linear spine
Not a branching tree. Every Maria-deployed V2 Federal token has exactly one Maria-deployed child (or is the OZZY terminal leaf). Ranking by child count is a uniform tiebreaker; effective ranking falls to `is_qing_underlying + smallest total_supply`.

### 3. Upstream conversion is mechanically possible
`target.Claim(ammo, K)` returns K of `target.Parent` per consumed ammo. So joey's V2 Federal bag is now effectively fungible across the FDIC↔DFM↔PARADE↔TLRz spine via accumulated 幹A / 幹B / 幹C ammo. The toll is 5K parent tokens per cycle (the K hold-back). FDIC↔FED conversion is not yet possible — would require deploying ammo with parent=FED.

### 4. PulseChain TX confirmation has long tails
Two cycles (2 and 7) had TX failures at the script's original gas/timeout settings:
- Cycle 2: TX confirmed eventually at ~7 minutes — exceeded 420s `wait_for_transaction_receipt` window.
- Cycle 7: TX **dropped** entirely from the mempool during a fee spike. 1.5× base_fee multiplier + 100K Beats priority wasn't enough.

**Patches landed in `tx_layer_c_cycle.py` (commit `c03d8da`):**
- `PRIORITY_FEE`: 100K → 200K Beats
- `max_fee` multiplier: 1.5× → 3.0× base
- `wait_for_transaction_receipt`: 420s → 1200s (with fallback poll: 60×5s → 180×5s, outer guard 720s → 2100s)

These changes are confined to Layer C. **`tx_layer_b_cycle.py` and `tx_dfm_cycle.py` remain on the original settings**, so if Task 11 (Layer B 100 cycles) launches without mirroring these patches, expect similar interruptions.

### 5. Recovery scripts work
The two ad-hoc recovery scripts (`/tmp/recover_cycle2.py`, `/tmp/recover_cycle7.py`) demonstrate the safe pattern for resuming a partial cycle: read on-chain state, identify exactly which TX are missing, submit only those. Both completed cleanly. The pattern is worth formalizing into a `tx_layer_c_resume.py` if Layer C scales further.

---

## Where we stopped

**Operational tasks remaining: 1**
- Task 11: Phase 3 Layer B 100 cycles at N=1M, K=100. ~3.5 hours, 1,100 TX, ~50 PLS gas, produces ~500M PARADE + 10K of each 幹B.

**Pre-launch decision required:**
Mirror the Layer C gas-param patches onto `tx_layer_b_cycle.py` BEFORE launching the 100-cycle loop. With 1,100 TX in flight, the chance of hitting at least one drop/timeout is high if running with the original 100K Beats priority + 1.5× max-fee + 420s timeout.

**Suggested patch:**
```python
# scripts/tx_layer_b_cycle.py — same edits as commit c03d8da on tx_layer_c_cycle.py
PRIORITY_FEE   = 200_000 * 10**9            # was 100_000
max_fee = max(int(base_fee * 3), ...)        # was * 1.5
receipt = ...wait_for_transaction_receipt(tx_hash, timeout=1200)  # was 420
for _ in range(180):                         # was 60
raise RuntimeError(f"... after 2100s ...")   # was 720s
```

After Layer B completes, the remaining open work is the Beat-Yuan acquisition plan (separate brainstorming target).

---

## Process meta-observation

The plan-write → spec-write → subagent-driven execution flow worked, but **the spec verification step in brainstorming was insufficient**. I confirmed the Yuan formula and its existence in the reward chain, but didn't trace which tokens were actually passed as the formula's argument until the user asked the question mid-execution. That single missed step would have caused us to permanently lock 168 trillion tokens worth of treasury bag if executed.

**Adjustment for next plan-verification:** when a plan claims "X widens Y," verify both the formula AND the call sites' arguments before approving the design. The handed-off plan was internally consistent given its (wrong) premise; only on-chain reads of the actual call graph caught the error.

---

## Commit log (this session, oldest → newest)

```
ebda118 docs(spec): YUE Cascade Pump — design spec
fc5720c docs(plan): YUE Cascade Pump — implementation plan
801c823 feat(recon): scaffold YUE cascade Phase 1 + Yuan sanity check
070570f feat(recon): YUE exit-mechanism check (Phase 1b)
74fcb91 refactor(recon): tighten check_exits — provenance, narrow excepts, helper extract
7c8522e feat(recon): V2 Federal tree re-scan with corrected parents (Phase 1c)
eadae6b feat(recon): holdings refresh + WITHOUT watchdog (Phase 1d)
9b6926f fix(recon): WITHOUT watchdog fails closed on read failure
93c4d19 chore(recon): refresh Phase 1 consolidated state at 2026-04-25
54bb0eb feat(park): scaffold tx_yue_park.py with --verify mode
40a2749 fix(park): cmd_verify is a true safety gate (PLS >= floor, Yuan gates exit, show exit verdicts)
36f2f27 feat(park): chunked YUE deposit with 40× Yuan delta assertions
16fcfba fix(park): receipt timeout 300s, w3_submit for post-state reads, drop unused import
6c59a62 feat(layer_b): wrapper loop with hard inter-cycle invariant assertions
43c80c6 feat(layer_c): target selection ranker (Phase 4)
54327f4 chore(layer_c): manual target override — TLRz selected (parent=PARADE)
70216f8 feat(layer_c): mirror tx_layer_b_cycle.py for Layer C target
ce739c3 chore(layer_c): deploy + probe complete (5 ammo live, TLRz accepts 幹C)
c03d8da fix(layer_c): harden gas params + receipt timeout after cycle 2/7 stalls
+ this report
```

20 + 1 commits total.

---

## Reference TX hashes

**Layer C deployment:**
- Approve: `0x6164b71aecdb18adca437c4a3aa959eca4880bb68d8747cf71e4b5c24ee82828`
- Probe mint: `0x7e0755c2d167c8ab715ee060faab9ee9f2dc3eacfe819f0d1dde749d34c37696`
- Probe claim: `0x1d13384811b46235373a8d79afa9ac61fd9f67ccc617f279e1ed9911e5a2cdb6`

**Cycle 7 recovery (the dropped-TX one):**
- Claim(幹C04, 999900) recovered: `0x1e32c2a6a3b01d671d9fd5ce922f595cb4121b0e068891753f445e6613297e5c`
- Claim(幹C05, 999900) recovered: `0x93e020bdf66583440b2c23f276fcb4fe2d33d82e81d604ad3c317baf3c93b7f5`

Full transaction trail in `/tmp/layer_c_10cycles.log`, `/tmp/layer_c_cycles3to10.log`, `/tmp/layer_c_cycles8to10.log` on the gibson VPS.
