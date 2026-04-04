# E7/E8 Minter Wallet Activation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get the Minter wallet's engines (E7 BACKBONE, E8 PHR3AK) operational so all 3 wallets generate PLS.

**Architecture:** E8 PHR3AK's ARM mode correctly sees OZZY+BAR as funded (6.4T OZZY, 18.2T BAR in TGSv8). It falls through to STITCH mode which takes 16.6s — killed by the 5s sim timeout. E7 BACKBONE passes `is_ready()` but OZZY has near-zero DEX value (1.5e-11 PLS/token), making spine running unprofitable. The fix has two parts: (1) make E8 STITCH actually complete its simulation, and (2) make E7 profitable by either finding better-value targets or dramatically increasing batch sizes to overcome gas costs.

**Tech Stack:** Python 3.13, web3.py, PulseChain RPC

---

## Investigation Findings (Read-Only)

### On-Chain State (verified block ~26,177,578)
```
TGSv8 OZZY:  6,432,214,154,419 tokens (6.4T)
TGSv8 BAR:  18,213,039,749,559 tokens (18.2T)
OZZY Debenture: True
OZZY DEX price: 0.000000000015476 PLS/token (~1.5e-11)
BAR DEX price:  0.000000000102590 PLS/token (~1.0e-10)
```

### Why Each Engine Is Stuck

**E8 PHR3AK** (Minter wallet):
- ARM mode: correctly skipped — both OZZY and BAR have balance > 0 in TGSv8
- DEPLOY mode: skipped — `deploy_queue` is empty in `phreak_config.json`
- STITCH mode: **runs but takes 16.6s** — killed by 5s sim timeout
- Result: `SimResult.failed("Timeout after 5.0s")` every cycle

**E7 BACKBONE** (Minter wallet):
- `is_ready()`: **True** — BAR balance > 0 in TGSv8
- `simulate()`: returns `(0, 0)` — OZZY is too cheap
  - 20 iterations x 1000 tokens x 1.5e-11 PLS = 0.0000003 PLS revenue
  - Gas cost: ~820 PLS
  - Revenue < gas cost by 9 orders of magnitude
- Result: SKIP confidence (unprofitable)

### Root Causes
1. **E8 timeout**: STITCH mode's graph scan takes 16.6s, default sim timeout is 5s
2. **E7 profitability**: OZZY has no meaningful DEX value — spine running generates tokens worth effectively 0 PLS
3. **E7 batch sizing**: `_size_iteration()` returns max 1000 tokens — even at 1M tokens per iteration, revenue is still negligible at current OZZY price

---

## File Structure

| File | Changes | Responsibility |
|------|---------|---------------|
| `scripts/Joystick/core/concurrency.py:28-33` | Modify | Add PHR3AK to `SIM_TIMEOUT_MAP` (20s) |
| `scripts/Joystick/engines/spine_runner.py:158-187` | Modify | Log WHY unprofitable, add massive batch mode |
| `scripts/Joystick/engines/spine_runner.py:133-156` | Modify | Add profitability diagnostic to is_ready log |
| `scripts/Joystick/engines/phreak.py:455-528` | Modify | ARM mode: skip balance check when both funded, proceed to STITCH faster |

---

### Task 1: Fix E8 PHR3AK Sim Timeout

**Files:**
- Modify: `scripts/Joystick/core/concurrency.py:28-33`

The STITCH mode graph scan takes 16.6s. The default sim timeout is 5s. PHR3AK needs at least 20s.

- [ ] **Step 1: Add PHR3AK to SIM_TIMEOUT_MAP**

In `scripts/Joystick/core/concurrency.py`, add PHR3AK to the timeout override map:

```python
SIM_TIMEOUT_MAP: dict[str, float] = {
    "Arb": 15.0,
    "TokenFactory": 15.0,
    "PHR3AK": 20.0,  # STITCH mode scans full token graph (~16s)
}
```

- [ ] **Step 2: Verify E8 sim completes**

Run:
```bash
set -a && source /opt/joystick/.env.pulse && set +a
python3 -c "
import sys; sys.path.insert(0, '/opt/joystick/repo')
from scripts.Joystick.engines.phreak import PhreakEngine
import time
e8 = PhreakEngine()
t0 = time.time()
try:
    p, g = e8.simulate()
    print(f'OK: mode={e8._pending_mode} profit={p/1e18:.1f} gas={g/1e18:.1f} ({time.time()-t0:.1f}s)')
except Exception as ex:
    print(f'FAIL ({time.time()-t0:.1f}s): {ex}')
"
```

Expected: `OK: mode=stitch profit=878.2 gas=878.2 (16-17s)` — completes within 20s timeout.

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/core/concurrency.py
git commit -m "fix: increase PHR3AK sim timeout to 20s for STITCH graph scan"
```

---

### Task 2: Add E7 Profitability Diagnostics

**Files:**
- Modify: `scripts/Joystick/engines/spine_runner.py:158-187`

E7 silently returns (0,0) when unprofitable. We need visibility into WHY and by how much.

- [ ] **Step 1: Add diagnostic logging to simulate()**

In `scripts/Joystick/engines/spine_runner.py`, replace the `simulate()` method body (lines 158-187) to add logging:

```python
def simulate(self) -> tuple[int, int]:
    """
    Estimate profit from one batch cycle on the best active spine.
    Returns (expected_profit_wei, estimated_gas_cost_wei).
    """
    self._refresh_spines()
    best = self._pick_best_spine()
    if not best:
        log.debug("E7: no best spine — all inactive or empty")
        return (0, 0)

    if not self._live_debenture_check(best):
        best.active = False
        log.info("E7: %s Debenture flipped to False — deactivated", best.label)
        return (0, 0)

    amount_per_iter = self._size_iteration(best)
    if amount_per_iter == 0:
        log.debug("E7: iteration size = 0 for %s", best.label)
        return (0, 0)

    child_out    = BATCH_ITERATIONS * amount_per_iter
    pls_expected = int(child_out * best.pls_per_child)

    gas_price = w3_read.eth.gas_price
    gas_cost  = int(SPINE_GAS_EST * gas_price * GAS_MULT)

    if pls_expected <= gas_cost:
        log.info("E7: %s unprofitable — revenue %.6f PLS vs gas %.1f PLS "
                 "(price=%.2e PLS/tok, batch=%d tok)",
                 best.label, pls_expected / 1e18, gas_cost / 1e18,
                 best.pls_per_child, child_out // 10**18)
        return (0, 0)

    return (pls_expected - gas_cost, gas_cost)
```

- [ ] **Step 2: Verify diagnostic output**

Run:
```bash
set -a && source /opt/joystick/.env.pulse && set +a
python3 -c "
import sys, logging; sys.path.insert(0, '/opt/joystick/repo')
logging.basicConfig(level=logging.INFO)
from scripts.Joystick.engines.spine_runner import SpineRunnerEngine
e7 = SpineRunnerEngine()
print(f'ready: {e7.is_ready()}')
p, g = e7.simulate()
print(f'profit={p/1e18:.6f} gas={g/1e18:.2f}')
"
```

Expected: Log line showing `E7: OZZY unprofitable — revenue 0.000000 PLS vs gas 820.1 PLS (price=1.54e-11 PLS/tok, batch=20000 tok)`

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/engines/spine_runner.py
git commit -m "fix: add E7 profitability diagnostics — log why spine is unprofitable"
```

---

### Task 3: Increase E7 Batch Size for Near-Zero Tokens

**Files:**
- Modify: `scripts/Joystick/engines/spine_runner.py` — `_size_iteration()` and constants

OZZY at 1.5e-11 PLS/token needs astronomical batch sizes to overcome gas. The current cap of 1000 tokens/iteration is far too low. With 18T BAR in TGSv8, we can afford massive iterations. The math:

- Gas cost: ~820 PLS
- To break even at 1.5e-11 PLS/token: need 820 / 1.5e-11 = 54.7 trillion tokens
- 20 iterations x tokens_per_iter must exceed 54.7T
- tokens_per_iter must be > 2.7T

With 18.2T BAR available, we can do ~9 iterations of 2T each before running out. But TGSv8 `batchMintAndClaim` has gas limits per call. We need to check what's practical.

- [ ] **Step 1: Check TGSv8 batchMintAndClaim gas limits**

Read `contracts/TGSv8.sol` to find the batchMintAndClaim function and understand its gas behavior with large token amounts. The V2 Federal `mint()` function takes an amount — minting 1T tokens in one call may use different gas than minting 1000 tokens.

Run a simulation to test:
```bash
set -a && source /opt/joystick/.env.pulse && set +a
python3 -c "
from web3 import Web3
from eth_abi import encode
from Crypto.Hash import keccak

w3 = Web3(Web3.HTTPProvider('https://rpc-pulsechain.g4mm4.io'))
TGSV8 = '0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32'
JOEY = '0x17367877aF5A8D0Eb33ba5689A880f696386E24D'
OZZY = '0x52b4F56d87765E7A9567E35bea97de13C3386554'
BAR = '0xaAE18Cd46C45d343BbA1eab46716B4D69d799734'

# Try estimate_gas for batchMintAndClaim with large amounts
# batchMintAndClaim(address token, uint256 count)
sel = keccak.new(data=b'batchMintAndClaim(address,uint256)', digest_bits=256).digest()[:4]
for count in [1, 10, 100]:
    calldata = '0x' + sel.hex() + encode(['address', 'uint256'], [OZZY, count]).hex()
    try:
        gas = w3.eth.estimate_gas({'from': JOEY, 'to': TGSV8, 'data': calldata})
        print(f'batchMintAndClaim(OZZY, {count}): {gas:,} gas')
    except Exception as e:
        print(f'batchMintAndClaim(OZZY, {count}): REVERT — {str(e)[:80]}')
"
```

- [ ] **Step 2: Update _size_iteration() and BATCH_ITERATIONS based on findings**

Based on gas limits found in Step 1, update the constants and sizing logic. The key change: when `pls_per_child` is extremely low (< 1e-6), use the maximum available parent balance divided by BATCH_ITERATIONS as the per-iteration amount, instead of the current 1000-token cap.

In `spine_runner.py`, find `_size_iteration()` and update:

```python
def _size_iteration(self, spine) -> int:
    """Size one mint-claim iteration based on available parent balance."""
    tgs = tgsv8_contract()
    parent_bal = safe(tgs, "bal", Web3.to_checksum_address(spine.parent)) or 0
    if parent_bal == 0:
        return 0

    # For near-zero value tokens, use maximum available balance
    # divided across iterations to maximize revenue per TX
    if spine.pls_per_child < 1e-6:
        # Use up to 1/BATCH_ITERATIONS of parent balance per iteration
        # This gives maximum throughput for cheap tokens
        max_per_iter = parent_bal // BATCH_ITERATIONS
        return max(max_per_iter, 10**18)  # minimum 1 whole token

    # Normal sizing for tokens with meaningful value
    per_iter = max(10**18, parent_bal // 10)
    return min(per_iter, 1000 * 10**18)
```

- [ ] **Step 3: Recalculate profitability with new batch size**

Run simulate again with the updated sizing to check if massive batches make OZZY profitable:

```bash
set -a && source /opt/joystick/.env.pulse && set +a
python3 -c "
import sys, logging; sys.path.insert(0, '/opt/joystick/repo')
logging.basicConfig(level=logging.INFO)
from scripts.Joystick.engines.spine_runner import SpineRunnerEngine
e7 = SpineRunnerEngine()
p, g = e7.simulate()
print(f'profit={p/1e18:.2f} PLS, gas={g/1e18:.2f} PLS')
"
```

Expected: Either profitable (revenue > 820 PLS gas) or still unprofitable — the math may not work at 1.5e-11 PLS/token even with 18T/20 = 900B tokens per iteration.

**Math check**: 20 iters x 900B tokens x 1.5e-11 PLS = 20 x 900e9 x 1.5e-11 = 20 x 0.0135 = 0.27 PLS. **Still far below 820 PLS gas.** OZZY spine running is economically dead at current prices.

- [ ] **Step 4: Commit**

```bash
git add scripts/Joystick/engines/spine_runner.py
git commit -m "fix: dynamic batch sizing for E7 — use max parent balance for cheap tokens"
```

---

### Task 4: Add Debenture Monitor Scan for Higher-Value Targets

**Files:**
- Modify: `scripts/Joystick/engines/phreak.py` — Debenture Monitor section

The OZZY spine is economically dead. The real path to E7 revenue is discovering NEW Debenture=True tokens with actual DEX value. The Debenture Monitor in E8 PHR3AK scans V2 Federal tokens periodically, but we need to verify it's running and check its output.

- [ ] **Step 1: Run Debenture Monitor manually**

```bash
set -a && source /opt/joystick/.env.pulse && set +a
python3 -c "
import sys, logging; sys.path.insert(0, '/opt/joystick/repo')
logging.basicConfig(level=logging.INFO)
from scripts.Joystick.engines.phreak import PhreakEngine
e8 = PhreakEngine()
# The monitor runs in _check_debenture_flips()
e8._check_debenture_flips()
"
```

Check output: any newly discovered Deb=True tokens beyond OZZY?

- [ ] **Step 2: Cross-reference V2 Federal tokens with DEX value**

Check all 14 known V2 Federal tokens (FDIC, DFM, PARADE, TLRz, JOB, SSA, SCOIETY, CAMPAIGN, OPIUM, BGDHTZ, TEHATER, ARMS, BAR, OZZY) for:
1. Debenture status (True/False)
2. DEX price (if any pair exists)

This tells us if any new Deb=True flips happened and whether they have value.

```bash
set -a && source /opt/joystick/.env.pulse && set +a
python3 -c "
import sys, json; sys.path.insert(0, '/opt/joystick/repo')
from web3 import Web3
from scripts.Joystick.core.chain import w3_read, safe, erc20
from Crypto.Hash import keccak

# Load V2 federal tokens
with open('scripts/Joystick/data/v2_federal_tokens.json') as f:
    data = json.load(f)

deb_sel = keccak.new(data=b'Debenture()', digest_bits=256).digest()[:4].hex()
for tok in data.get('tokens', data) if isinstance(data, dict) else data:
    addr = tok.get('address', tok) if isinstance(tok, dict) else tok
    sym = tok.get('symbol', '?') if isinstance(tok, dict) else '?'
    try:
        result = w3_read.eth.call({'to': Web3.to_checksum_address(addr), 'data': '0x' + deb_sel})
        deb = bool(int(result.hex(), 16))
        print(f'{sym:12s} Deb={deb}  {addr}')
    except:
        print(f'{sym:12s} Deb=ERROR  {addr}')
"
```

- [ ] **Step 3: Document findings and commit**

Record which V2 Federal tokens have Deb=True and their DEX values. If any new high-value targets exist, add them to `phreak_config.json`.

```bash
git add scripts/Joystick/engines/phreak.py scripts/Joystick/data/phreak_config.json
git commit -m "recon: scan V2 Federal Debenture status for E7 spine targets"
```

---

### Task 5: Enable E8 STITCH on Minter Wallet

**Files:**
- Modify: `scripts/Joystick/engines/phreak.py` — STITCH confidence
- Modify: `scripts/Joystick/core/strategist.py` — wallet routing

With the sim timeout fixed (Task 1), E8 STITCH will complete and return a valid SimResult. STITCH creates new LP pairs between existing tokens — this creates new arb edges for E1 RAZOR on the Seller wallet, even if E7 stays unprofitable.

- [ ] **Step 1: Verify STITCH SimResult with increased timeout**

After Task 1 is applied:
```bash
set -a && source /opt/joystick/.env.pulse && set +a
python3 -c "
import sys; sys.path.insert(0, '/opt/joystick/repo')
from scripts.Joystick.engines.phreak import PhreakEngine
e8 = PhreakEngine()
sr = e8.sim_result()
print(f'success={sr.success} mode={sr.mode} confidence={sr.confidence}')
print(f'profit={sr.profit_wei/1e18:.1f} gas={sr.gas_wei/1e18:.1f}')
print(f'notes={sr.notes}')
"
```

Expected: `success=True mode=stitch confidence=... profit=878.2 gas=878.2`

- [ ] **Step 2: Run full bot cycle with --dry-run to verify Minter wallet gets E8**

```bash
set -a && source /opt/joystick/.env.pulse && set +a
python3 -m scripts.Joystick.bot --dry-run --once 2>&1 | grep -i "minter\|PHR3AK\|stitch\|E8"
```

Expected: Strategist recommends E8 PHR3AK for Minter wallet (STITCH mode), not SKIP.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: E8 STITCH mode operational on Minter wallet"
```

---

## Summary

| Task | Effect | Wallet Activated |
|------|--------|-----------------|
| 1. Fix E8 sim timeout | E8 STITCH completes simulation | Minter (E8) |
| 2. E7 diagnostics | Visibility into why E7 is unprofitable | — (observability) |
| 3. E7 batch sizing | Maximize throughput for cheap tokens | Minter (E7) — likely still unprofitable |
| 4. Debenture scan | Find higher-value spine targets | Minter (E7) — future |
| 5. E8 STITCH activation | Creates new arb edges for E1 | Minter (E8) + Seller (E1) |

**Critical insight**: OZZY spine running (E7) is economically dead at 1.5e-11 PLS/token — no batch size can overcome ~820 PLS gas cost. The real value from the Minter wallet comes from **E8 STITCH** (creating LP pairs that open arb surfaces for E1 RAZOR on the Seller wallet). Task 1 is the highest-impact fix.
