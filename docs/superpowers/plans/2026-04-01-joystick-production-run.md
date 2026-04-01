# Joystick Production Run — Bug Fixes + Engine Activation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix known bugs, then activate Joystick engines E2/E6/E8/E7 to generate PLS toward the 32M validator goal.

**Architecture:** Fix 4 core bugs (env path, sell queue safety, docstring accuracy, sweep comment), then sequentially activate engines by confidence: E2 CEREAL (highest ROI, ~1,190 PLS/cycle), E6 DaVINCI (treasury sniping, 1-10K PLS/batch), E8 ARM (100 PLS buy → unlocks E7), E7 BACKBONE (infinite mint-claim loops). Each engine gets a dry-run smoke test before live execution.

**Tech Stack:** Python 3.11+, web3.py 6+, PulseChain (369), EIP-1559 Type 2 TXs

**Engines explicitly excluded:** E3 MERIDIAN (Beat), E5 ABUPRU (LAU) — per user request.

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `scripts/Joystick/bot.py:5-11` | Fix E6 wallet label in docstring header |
| Modify | `scripts/Joystick/bot.py:52` | Make .env.pulse path portable |
| Modify | `scripts/Joystick/core/sell_queue.py:74-76` | Add multicall length validation |
| Modify | `scripts/Joystick/core/wallet_manager.py:296` | Add safety comment on sweep skip-simulate |
| None | `scripts/Joystick/engines/dss.py` | E2 — already wired, verify via dry-run |
| None | `scripts/Joystick/engines/treasury_sniper.py` | E6 — already wired, verify via dry-run |
| None | `scripts/Joystick/engines/phreak.py` | E8 — already wired, verify ARM via dry-run |
| None | `scripts/Joystick/engines/spine_runner.py` | E7 — blocked until E8 ARM completes |

---

### Task 1: Fix hardcoded .env.pulse path in bot.py

**Files:**
- Modify: `scripts/Joystick/bot.py:51-53`

- [ ] **Step 1: Read current code**

Read `scripts/Joystick/bot.py` lines 50-54 to confirm the hardcoded path.

- [ ] **Step 2: Apply fix — make .env.pulse path portable**

Replace lines 51-53:

```python
from dotenv import load_dotenv
load_dotenv("/opt/joystick/.env.pulse")
load_dotenv()  # also check cwd for overrides
```

With:

```python
from dotenv import load_dotenv
# Load .env.pulse: try repo-relative path first, then hardcoded VPS path, then cwd
_env_candidates = [
    os.path.join(os.path.dirname(__file__), "..", "..", ".env.pulse"),
    "/opt/joystick/.env.pulse",
]
for _env_path in _env_candidates:
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
        break
load_dotenv()  # also check cwd for overrides
```

- [ ] **Step 3: Verify the fix doesn't break imports**

Run: `cd /opt/joystick/repo && python -c "from scripts.Joystick.core.config import JOEY_WALLET; print('config OK:', JOEY_WALLET[:10])"`

Expected: `config OK: 0x17367877` (or similar truncated address)

- [ ] **Step 4: Commit**

```bash
git add scripts/Joystick/bot.py
git commit -m "fix: make .env.pulse path portable instead of hardcoded VPS path

Searches repo-relative and VPS paths before falling back to cwd.
Prevents startup failure if repo is relocated.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Fix sell_queue.py multicall length safety

**Files:**
- Modify: `scripts/Joystick/core/sell_queue.py:74-76`

- [ ] **Step 1: Read current code**

Read `scripts/Joystick/core/sell_queue.py` lines 68-80 to confirm the multicall index access pattern.

- [ ] **Step 2: Apply fix — add multicall result length validation**

Insert validation after line 73 (after the `try/except` block that catches multicall failure), before the `targets = []` line:

```python
        # Guard against partial multicall results
        if len(balances) != len(known_tokens):
            log.warning("SellQueue multicall partial: got %d/%d results",
                        len(balances), len(known_tokens))
            return self._targets
```

So the full block reads:

```python
        try:
            balances = multicall(contracts)
        except Exception as exc:
            log.warning("SellQueue multicall failed: %s", exc)
            return self._targets

        # Guard against partial multicall results
        if len(balances) != len(known_tokens):
            log.warning("SellQueue multicall partial: got %d/%d results",
                        len(balances), len(known_tokens))
            return self._targets

        targets = []
        for i, (addr, symbol) in enumerate(known_tokens):
```

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/core/sell_queue.py
git commit -m "fix: guard sell_queue multicall against partial results

If multicall returns fewer results than tokens sent, return cached
targets instead of risking IndexError.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Fix bot.py docstring — E6 wallet label is wrong

**Files:**
- Modify: `scripts/Joystick/bot.py:10`

- [ ] **Step 1: Read the header docstring**

Read `scripts/Joystick/bot.py` lines 1-13. Line 10 says:
```
  Engine 6 — DaVINCI:         Treasury sniping via recon data                [Minter]
```

But E6 uses the Joey wallet (per `ENGINE_WALLET_ROLES` in `engines/base.py` and `treasury_sniper.py`).

- [ ] **Step 2: Fix the wallet label**

Change line 10 from `[Minter]` to `[Joey]`:

```python
  Engine 6 — DaVINCI:         Treasury sniping via recon data                [Joey]
```

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/bot.py
git commit -m "fix: correct E6 DaVINCI wallet label in bot.py docstring

E6 routes through Joey wallet, not Minter. Docstring was stale from
pre-session-16 when TGSv8 balance gate was removed.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Document sweep skip-simulate rationale

**Files:**
- Modify: `scripts/Joystick/core/wallet_manager.py:~296`

- [ ] **Step 1: Read the sweep TX code**

Read `scripts/Joystick/core/wallet_manager.py` lines 285-300 to find the exact sweep TX submission.

- [ ] **Step 2: Add safety comment**

Add a comment above the `sign_transaction` / `send_raw` call explaining why simulation is skipped:

```python
            # Sweep is a plain ETH transfer (21K gas, zero revert risk).
            # Skip simulation for performance — nonce already tracked by WalletNonce.
```

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/core/wallet_manager.py
git commit -m "docs: document why sweep TX skips simulation

Plain ETH transfer has no revert risk; simulation would add latency
for zero safety benefit.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Smoke-test bot startup + dry-run cycle

**Files:**
- None modified — verification only

- [ ] **Step 1: Verify Python imports resolve**

Run from repo root:

```bash
cd /opt/joystick/repo
python -c "
from scripts.Joystick.engines.dss import DSSEngine
from scripts.Joystick.engines.treasury_sniper import TreasurySniperEngine
from scripts.Joystick.engines.phreak import PhreakEngine
from scripts.Joystick.engines.spine_runner import SpineRunnerEngine
from scripts.Joystick.engines.arb import ArbEngine
from scripts.Joystick.engines.token_factory import TokenFactoryEngine
print('All engine imports OK')
"
```

Expected: `All engine imports OK`

- [ ] **Step 2: Run bot --status to verify engine readiness**

```bash
cd /opt/joystick/repo
python -m scripts.Joystick.bot --status 2>&1 | head -60
```

Expected output shows 8 engines with their status (Ready/Wired/Blocked/Disabled). Key checks:
- E2 CEREAL: should show "Wired" or "Ready"
- E6 DaVINCI: should show "Wired" or "Ready"
- E8 PHR3AK: should show "Ready"
- E7 BACKBONE: should show "Blocked"

- [ ] **Step 3: Run bot --wallet-status to verify wallet config**

```bash
python -m scripts.Joystick.bot --wallet-status 2>&1
```

Expected: Shows Joey wallet address `0x1736...`, PLS balance ~1.98M, and Minter/Seller status (configured or "not set").

- [ ] **Step 4: Run one dry-run cycle**

```bash
python -m scripts.Joystick.bot --dry-run --once 2>&1 | tail -40
```

Expected: Completes one simulation cycle without sending TXs. Shows strategist recommendation. No crashes, no unhandled exceptions.

---

### Task 6: Activate E2 CEREAL — Hub Harvest (HIGHEST CONFIDENCE)

**Files:**
- None modified — execution + verification

**Prerequisites:** Tasks 1-5 complete. Hub V2 deployed at `0x400D052F...`. GIBS/WPLS V2 pair exists.

**Economics:** Per cycle: mint 17 GIBS → LP 50% (~1,678 PLS position) + sell 50% (~1,580 PLS) - gas (~390 PLS) = **~1,190 PLS net + LP value**.

- [ ] **Step 1: Verify E2 prerequisites via dry-run**

```bash
python -m scripts.Joystick.bot --e2-only --dry-run --once 2>&1
```

Expected: E2 CEREAL simulation shows positive profit estimate. Check output for:
- `primeGibs` gas estimate
- `mintLPAndSell` expected PLS output
- AFF balance check (needs >=17 AFF in Hub or wallet)
- GIBS/WPLS V2 reserves (non-zero)

If AFF balance is insufficient, E2 will report needing AFF acquisition first (the engine handles this internally via `_acquire_aff()`).

- [ ] **Step 2: Run E2 live — single cycle**

```bash
python -m scripts.Joystick.bot --e2-only --once 2>&1
```

Expected: Two TXs submitted:
1. `primeGibs(17)` — ~200K gas
2. `mintLPAndSell(...)` — ~550K gas

Monitor output for TX hashes and PLS profit/loss.

- [ ] **Step 3: Verify on-chain results**

After TX confirmation, verify:
- Joey PLS balance increased (net profit after gas)
- GIBS/WPLS V2 LP position deepened
- No revert errors in logs

- [ ] **Step 4: Document E2 results**

Record the actual profit/loss, gas costs, and TX hashes in the event log. If profitable, E2 is confirmed operational.

---

### Task 7: Activate E6 DaVINCI — Treasury Sniping

**Files:**
- None modified — execution + verification

**Prerequisites:** Tasks 1-5 complete. `data/recon_results.json` exists (39K lines).

**Economics:** Realistic ~1-10K PLS per profitable batch. Depends on current treasury token backing levels.

- [ ] **Step 1: Check recon data freshness**

```bash
python -c "
import json, os, time
path = 'scripts/Joystick/data/recon_results.json'
if os.path.exists(path):
    mtime = os.path.getmtime(path)
    age_hours = (time.time() - mtime) / 3600
    with open(path) as f:
        data = json.load(f)
    print(f'Recon data: {len(data.get(\"results\", data))} entries, age: {age_hours:.1f}h')
else:
    print('NO RECON DATA — run treasury_recon.py first')
"
```

If data is >24h stale, E6 will auto-trigger a refresh (subprocess call to `treasury_recon.py`, 300s timeout). Alternatively, run recon manually:

```bash
python scripts/Joystick/data/treasury_recon.py 2>&1 | tail -20
```

- [ ] **Step 2: Dry-run E6 to check for profitable targets**

```bash
python -m scripts.Joystick.bot --e6-only --dry-run --once 2>&1
```

Expected: E6 simulation shows either:
- **Profitable targets found**: lists target tokens, estimated PLS output, batch size
- **No profitable targets**: all backing levels below threshold (MIN_PROFIT_PLS=100)

If no profitable targets, E6 is correctly gated. Skip to Task 8.

- [ ] **Step 3: Run E6 live (if profitable targets exist)**

```bash
python -m scripts.Joystick.bot --e6-only --once 2>&1
```

Expected: `batchClaimTreasury()` TX submitted. Monitor for:
- Claim TX hash
- Actual PLS received vs. estimate
- Gas cost

- [ ] **Step 4: Document E6 results**

Record actual yield, target tokens claimed, and any discrepancies from simulation.

---

### Task 8: Activate E8 PHR3AK ARM — Unlock E7 BACKBONE

**Files:**
- None modified — execution + verification

**Prerequisites:** Tasks 1-5 complete. `data/phreak_config.json` exists with `deb_true_v2` containing OZZY.

**Economics:** 100 PLS investment (buy OZZY) → deposits into TGSv8 → unlocks E7 BACKBONE for infinite mint-claim loops.

- [ ] **Step 1: Verify phreak_config.json has ARM targets**

```bash
python -c "
import json
with open('scripts/Joystick/data/phreak_config.json') as f:
    cfg = json.load(f)
deb = cfg.get('deb_true_v2', [])
print(f'Deb=true tokens: {len(deb)}')
for t in deb:
    print(f'  {t.get(\"symbol\", \"?\")}: {t.get(\"address\", \"?\")}')
print(f'ARM default PLS: {cfg.get(\"arm_default_pls\", \"not set\")}')
"
```

Expected: At least OZZY listed. `arm_default_pls` = 100.

- [ ] **Step 2: Dry-run E8 ARM**

```bash
python -m scripts.Joystick.bot --engine PHR3AK --dry-run --once 2>&1
```

Expected: E8 simulation shows ARM mode selected (OZZY balance = 0 in TGSv8), estimated gas for `swapNativeForTokens()`, and 100 PLS cost.

**Note:** If the bot doesn't support `--engine PHR3AK` flag, use the full bot in dry-run:

```bash
ENGINE_EXCLUDE="Arb,Beat,LAU,DSS,TokenFactory,TreasurySniper,SpineRunner" \
  python -m scripts.Joystick.bot --dry-run --once 2>&1
```

- [ ] **Step 3: Run E8 ARM live**

```bash
ENGINE_EXCLUDE="Arb,Beat,LAU,DSS,TokenFactory,TreasurySniper,SpineRunner" \
  python -m scripts.Joystick.bot --once 2>&1
```

Expected: One TX: `TGSv8.swapNativeForTokens(OZZY, minOut, router, dex)` with 100 PLS value. OZZY tokens land in TGSv8 working balance.

- [ ] **Step 4: Verify OZZY landed in TGSv8**

```bash
python -c "
from scripts.Joystick.core.chain import w3_read, erc20, safe
TGSV8 = '0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32'
OZZY = '0x...'  # fill from phreak_config.json
bal = safe(erc20(OZZY), 'balanceOf', TGSV8)
print(f'TGSv8 OZZY balance: {bal / 1e18:.6f}')
"
```

Expected: Non-zero OZZY balance in TGSv8.

- [ ] **Step 5: Commit any config changes**

If `phreak_config.json` was updated by E8 (it persists ARM state atomically), commit:

```bash
git add scripts/Joystick/data/phreak_config.json
git commit -m "data: E8 PHR3AK ARM completed — OZZY deposited into TGSv8

Unlocks E7 BACKBONE for Debenture=True mint-claim loops.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Activate E7 BACKBONE — Spine Running (unlocked by E8)

**Files:**
- None modified — execution + verification

**Prerequisites:** Task 8 complete (OZZY in TGSv8). E7 BACKBONE should now report "Ready" instead of "Blocked".

**Economics:** OZZY PLS/token is near-zero (~1.54e-11). E7 will run, but profit depends on accumulated OZZY volume and DEX liquidity. The real value is proving the pipeline works — higher-value Deb=true tokens found by the Debenture Monitor will be the revenue driver.

- [ ] **Step 1: Verify E7 is no longer blocked**

```bash
python -m scripts.Joystick.bot --status 2>&1 | grep -i backbone
```

Expected: E7 BACKBONE shows "Ready" (was "Blocked" before E8 ARM).

- [ ] **Step 2: Dry-run E7**

```bash
ENGINE_EXCLUDE="Arb,Beat,LAU,DSS,TokenFactory,TreasurySniper,PHR3AK" \
  python -m scripts.Joystick.bot --dry-run --once 2>&1
```

Expected: E7 simulation shows OZZY mint-claim loop, estimated gas, and (likely tiny) profit estimate.

- [ ] **Step 3: Run E7 live (if simulation succeeds)**

```bash
ENGINE_EXCLUDE="Arb,Beat,LAU,DSS,TokenFactory,TreasurySniper,PHR3AK" \
  python -m scripts.Joystick.bot --once 2>&1
```

Expected: `batchMintAndClaim(OZZY, count)` TX. Even if profit is negligible, this validates the entire E8→E7 pipeline.

- [ ] **Step 4: Document E7 results**

Record: TX hash, gas cost, tokens minted/claimed, sell output (if any). Note whether the pipeline is viable at current OZZY prices or awaiting higher-value Deb=true tokens.

---

### Task 10: Run full bot cycle with all active engines

**Files:**
- None modified — integration verification

**Prerequisites:** Tasks 1-9 complete. All bugs fixed, E2/E6/E8/E7 individually verified.

- [ ] **Step 1: Run one full cycle (excluding E3/E5)**

```bash
ENGINE_EXCLUDE="Beat,LAU" \
  python -m scripts.Joystick.bot --once 2>&1
```

Expected: Strategist evaluates all 6 remaining engines, recommends top action(s), executes. Verify:
- Gas guard passes (PLS > 100K)
- Parallel simulation completes (~300ms)
- Strategist selects highest-ROI engine (likely E2)
- TX succeeds and profit is logged
- Adaptive delay adjusts based on result

- [ ] **Step 2: Verify event log**

```bash
ls -la scripts/Joystick/data/events/
tail -5 scripts/Joystick/data/events/*.jsonl 2>/dev/null || echo "No event logs yet"
```

Expected: JSON-L event log with cycle data, engine results, profit/loss.

- [ ] **Step 3: Push all fixes + documented results**

```bash
git push origin claude/joystick-V2-FanxJ
```

---

### Task 11: Start continuous bot operation

**Files:**
- None modified — operational deployment

**Prerequisites:** Task 10 complete. Full cycle verified.

- [ ] **Step 1: Start bot in auto mode (excluding E3/E5)**

```bash
ENGINE_EXCLUDE="Beat,LAU" \
  python -m scripts.Joystick.bot 2>&1 | tee /tmp/joystick_$(date +%Y%m%d).log
```

Or via systemd if on VPS:

```bash
sudo systemctl start joystick-bot
sudo systemctl status joystick-bot
```

- [ ] **Step 2: Monitor first 5 cycles**

Watch for:
- Consistent E2 profits (~1,190 PLS/cycle)
- Gas costs within expected range (~390 PLS)
- No repeated failures or circuit breaker trips
- Adaptive delay stabilizing

- [ ] **Step 3: Verify PLS accumulation trend**

After 5+ cycles, check PLS balance growth:

```bash
python -m scripts.Joystick.bot --wallet-status
```

Expected: PLS balance increasing from ~1,979,625 baseline. At E2's projected rate:
- Per cycle: ~1,190 PLS net
- Per hour (30s cycles): ~142,800 PLS/hour
- Per day: ~3.4M PLS/day

**Time to 32M PLS goal at E2 rate: ~9 days** (optimistic, assumes continuous operation + no gas spikes).

---

## Execution Order & Dependencies

```
Task 1 (env fix) ──┐
Task 2 (sell_queue) ├─→ Task 5 (smoke test) ─→ Task 6 (E2) ─→ Task 10 (full cycle) ─→ Task 11 (continuous)
Task 3 (docstring) ─┤                         Task 7 (E6) ─┘                ↑
Task 4 (sweep doc) ─┘                         Task 8 (E8 ARM) ─→ Task 9 (E7) ─┘
```

Tasks 1-4 are independent (parallelize). Task 5 depends on all 4. Tasks 6-9 depend on 5 but are independent of each other (parallelize where possible). Task 10 depends on 6-9. Task 11 depends on 10.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| AFF insufficient for E2 | Medium | E2 delayed | Engine auto-acquires AFF via `_acquire_aff()` — costs ~45 PLS/AFF |
| No profitable E6 targets | High | E6 idle | Expected — E6 monitors continuously, executes when targets appear |
| OZZY too low-value for E7 profit | High | E7 unprofitable | Pipeline validation is the goal; Debenture Monitor watches for flips |
| Gas spike during execution | Low | Cycle skipped | Gas guard + ceiling check abort automatically |
| RPC timeout during multicall | Low | Cycle retries | RPCPool with circuit breakers handles this |

## PLS Accumulation Projections

| Scenario | Daily PLS | Days to 32M | Notes |
|----------|-----------|-------------|-------|
| E2 only (30s cycles) | ~3.4M | ~9 days | Assumes continuous, no gas spikes |
| E2 + E6 (occasional snipes) | ~3.5M+ | ~8 days | E6 adds 1-10K PLS per batch |
| E2 + E7 (after Deb flip) | ~4M+ | ~7 days | Depends on token values |
| Conservative (50% uptime) | ~1.7M | ~18 days | Realistic with maintenance windows |
