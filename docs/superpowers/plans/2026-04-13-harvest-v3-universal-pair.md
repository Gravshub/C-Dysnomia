# HarvestV3: Universal Pair Module — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy a new HarvestModule with `mintLPAndSellPair()` — an atomic prime→purchase→LP→sell function that works with ANY LAU token and ANY LP partner, replacing the hardcoded GIBS/WPLS-only `mintLPAndSell()`.

**Architecture:** The function is already written in `contracts/JoystickHub.sol`. We compile the updated HarvestModule, deploy it on-chain, register its selector on the Hub proxy via `batchRegisterModule()`, then wire E2's engine to call it for GIBS/AFF cycles. The existing `mintLPAndSell` stays active for GIBS/WPLS — both coexist.

**Tech Stack:** Solidity 0.8.21 (py-solc-x), Python web3.py, PulseChain (369)

---

### Task 1: Compile the updated HarvestModule

**Files:**
- Read: `contracts/JoystickHub.sol` (already modified — `mintLPAndSellPair` added)
- Create: `build/HarvestV3/combined.json` (compiled artifact)
- Modify: `scripts/deploy_joystick_hub.py:78-83` (add new selector to HARVEST_FUNCTIONS)

- [ ] **Step 1: Dry-run compile to verify the contract builds**

```bash
python3 scripts/deploy_joystick_hub.py --dry-run
```

Expected: All 4 contracts compile, HarvestModule stays under 24,576 bytes (EIP-170 limit). The new `mintLPAndSellPair` function should appear in HarvestModule's function list.

- [ ] **Step 2: Add `mintLPAndSellPair` to HARVEST_FUNCTIONS in deploy script**

In `scripts/deploy_joystick_hub.py`, add the new function signature to `HARVEST_FUNCTIONS` so the deploy script knows to register it:

```python
HARVEST_FUNCTIONS = [
    "primeGibs(uint256)",
    "mintLPAndSell(uint256,uint256,uint256,uint8,uint256,address[],uint8)",
    "mintLPAndSellPair(address,address,address,uint256,uint256,uint256,uint256,uint8,uint256,address[],uint8)",
    "batchReseed(address[],uint256[])",
    "harvestConfig()",
]
```

- [ ] **Step 3: Verify the selector is correct**

```python
python3 -c "
from web3 import Web3
sig = 'mintLPAndSellPair(address,address,address,uint256,uint256,uint256,uint256,uint8,uint256,address[],uint8)'
selector = Web3.keccak(text=sig)[:4].hex()
print(f'Selector: 0x{selector}')
print(f'Signature: {sig}')
"
```

- [ ] **Step 4: Save compiled artifact for deployment**

```bash
python3 -c "
from scripts.deploy_joystick_hub import ensure_solc, compile_contracts
from pathlib import Path
import json

source = Path('contracts/JoystickHub.sol').read_text()
ensure_solc()
contracts = compile_contracts(source)
abi, bytecode = contracts['HarvestModule']

out = Path('build/HarvestV3')
out.mkdir(parents=True, exist_ok=True)
(out / 'combined.json').write_text(json.dumps({'abi': abi, 'bytecode': bytecode}, indent=2))
print(f'Saved to {out}/combined.json ({len(bytecode)//2} bytes)')
"
```

- [ ] **Step 5: Commit**

```bash
git add contracts/JoystickHub.sol scripts/deploy_joystick_hub.py build/HarvestV3/
git commit -m "feat(hub): add mintLPAndSellPair — universal LAU + any pair atomic harvest

mintLPAndSellPair(lau, paymentToken, lpPartner, primeCount, purchaseAmt,
  lpBps, burnBps, lpDex, minSellOut, sellPath, sellDex)

Fully generic: no hardcoded tokens, no config reads. Everything passed
as parameters. Works with GIBS today, next LAU tomorrow.

Includes compiled HarvestV3 artifact for deployment."
```

---

### Task 2: Create the module-only deploy script

**Files:**
- Create: `scripts/deploy_harvest_v3.py`
- Reference: `scripts/deploy_floor_harvest_module.py` (same pattern)

- [ ] **Step 1: Write the deploy script**

Create `scripts/deploy_harvest_v3.py` following the exact pattern from `deploy_floor_harvest_module.py`:

1. Load compiled artifact from `build/HarvestV3/combined.json`
2. Deploy HarvestModule contract (no constructor args — it's a delegatecall target)
3. Call `hub.batchRegisterModule([selector], moduleAddress)` to register `mintLPAndSellPair`
4. Verify by calling the Hub with the new selector

The script should:
- Support `--dry-run` (print plan without deploying)
- Use EIP-1559 Type 2 TXs with GAS_MULT=2.5
- Print the deployed address and registration TX
- Estimate total gas cost before deploying

Key: only the `mintLPAndSellPair` selector gets registered on the NEW module. All existing selectors (`mintLPAndSell`, `primeGibs`, etc.) stay on the current HarvestV2 module. Both coexist.

- [ ] **Step 2: Dry-run the deploy script**

```bash
python3 scripts/deploy_harvest_v3.py --dry-run
```

Expected: prints estimated gas cost, selector to register, artifact size.

- [ ] **Step 3: Commit**

```bash
git add scripts/deploy_harvest_v3.py
git commit -m "feat(deploy): add deploy_harvest_v3.py — module-only HarvestV3 deploy"
```

---

### Task 3: Deploy to PulseChain mainnet

**Prerequisite:** Joey runs this with wallet key loaded.

- [ ] **Step 1: Deploy**

```bash
source /opt/joystick/.env.pulse  # or ensure DYSNOMIA_PRIVATE_KEY is set
python3 scripts/deploy_harvest_v3.py
```

Expected output:
```
[1/3] Deploying HarvestModule...
  -> 0x<NEW_ADDRESS>  (gas: ~XXX, cost: ~XXX PLS)
[2/3] Registering mintLPAndSellPair selector on Hub...
  TX: 0x<HASH>
[3/3] Verification...
  mintLPAndSellPair callable: OK
```

- [ ] **Step 2: Record deployed address**

Update `scripts/Joystick/core/config.py`:
```python
HARVEST_V3_MODULE = "0x<DEPLOYED_ADDRESS>"
```

Update `contracts/JoystickHub.sol` header comment with new module address.

- [ ] **Step 3: Test on-chain — call mintLPAndSellPair with GIBS/AFF**

```bash
python3 -m scripts.Joystick.bot --e2-only  # should now use mintLPAndSellPair for GIBS/AFF
```

Verify:
- Hub calls `mintLPAndSellPair(GIBS_LAU, AFF, AFF, 17, 17, 7000, 0, 1, ...)` atomically
- 1 TX instead of 5-6 TXs
- Gas ~300K instead of ~2.5M (no separate primeGibs TX)

- [ ] **Step 4: Commit deployment record**

```bash
git add scripts/Joystick/core/config.py
git commit -m "chore(deploy): HarvestV3 deployed at 0x<ADDRESS> — block <BLOCK>"
```

---

### Task 4: Wire E2 engine to use `mintLPAndSellPair` for GIBS/AFF

**Files:**
- Modify: `scripts/Joystick/engines/dss.py` — add `_execute_harvest_pair()` method
- Modify: `scripts/Joystick/core/chain.py` — add Hub ABI entry for `mintLPAndSellPair`

- [ ] **Step 1: Add mintLPAndSellPair to Hub ABI**

In `scripts/Joystick/core/chain.py`, add the new function to the Hub ABI or the merged ABI JSON at `data/abis/joystick_hub.json` (the deploy script regenerates this).

- [ ] **Step 2: Add `_execute_harvest_pair()` to DSSEngine**

New method in `engines/dss.py` that calls `mintLPAndSellPair` atomically:

```python
def _execute_harvest_pair(self, lau, payment_token, lp_partner,
                           prime_count, purchase_amt, lp_bps,
                           sell_path, sell_dex, min_sell_out,
                           dry_run=False) -> EngineResult:
    """
    Atomic harvest on any LAU/pair via Hub mintLPAndSellPair.
    Single TX: prime → purchase → LP → sell.
    """
    hub = self._get_hub_submit()
    r = send_tx(
        hub.functions.mintLPAndSellPair(
            lau, payment_token, lp_partner,
            prime_count, purchase_amt,
            lp_bps, 0,  # burnBps=0
            1,  # lpDex=V2
            min_sell_out, sell_path, sell_dex,
        ),
        f"mintLPAndSellPair({purchase_amt} {lau[-6:]}/{lp_partner[-6:]})",
        dry_run=dry_run, gas_tier="fast",
    )
    ...
```

- [ ] **Step 3: Wire into the grow-pair / pump loop**

Replace the multi-TX sequence (wrap + swap + prime + purchase + deposit + addLiquidity) with a single `_execute_harvest_pair()` call. The Hub handles everything atomically.

- [ ] **Step 4: Test — run 3 cycles, verify 1-TX atomic execution**

```bash
python3 -m scripts.Joystick.bot --pump  # or --grow-pair
```

Verify each cycle is 1 Hub TX instead of 6. Gas should drop from ~3,000 PLS to ~300 PLS per cycle.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/engines/dss.py scripts/Joystick/core/chain.py
git commit -m "feat(e2): wire mintLPAndSellPair — atomic GIBS/AFF harvest in 1 TX"
```

---

### Task 5: Build the balanced spread engine

**Files:**
- Modify: `scripts/Joystick/bot.py` — update `--pump` to use atomic cycles
- Modify: `scripts/Joystick/engines/dss.py` — impact-sized sells

- [ ] **Step 1: Calculate arb-trigger sell size from pool reserves**

The sell must create enough impact to guarantee arb response. From probe data:
- Arb bot gas: ~227 PLS
- Need: trade profit > 227 PLS for the arb bot
- Formula: `sell_gibs = R_gibs * target_impact_pct / 200` (for target_impact_pct% price impact)
- At 1% impact on 6,600 GIBS reserve = 33 GIBS → ~400 PLS arb profit (covers 227 gas)

Add to `dss.py`:
```python
def _arb_trigger_size(self, pair_addr, target_impact_pct=1.0) -> int:
    """GIBS amount that creates target_impact_pct% on the given pair."""
    reserves = self._read_pair_reserves(pair_addr)
    if not reserves or reserves[0] == 0:
        return 0
    R_gibs = reserves[0]
    # From solve_for_impact: x = R * (sqrt(1+p) - 1) / 0.997
    import math
    p = target_impact_pct / 100
    x = R_gibs * (math.sqrt(1 + p) - 1) / 0.997
    return int(x)
```

- [ ] **Step 2: Update `--pump` to use atomic cycles with impact-sized actions**

Each cycle:
1. `mintLPAndSellPair(GIBS, AFF, AFF, N, N, 7000, ...)` — atomic mint + 70% LP + 30% sell
2. Where N = `_arb_trigger_size()` ÷ 0.3 (so the 30% sell portion = trigger size)
3. Probe records sell, watches for arb
4. On arb detection → next cycle's LP locks the corrected price
5. P&L: mint cost (N AFF) vs sell revenue (0.3N GIBS × DEX price) + LP position value

- [ ] **Step 3: Add P&L tracking to each cycle**

```python
# Per cycle:
mint_cost_pls = purchase_amt * aff_price_pls
sell_revenue_pls = sell_received / 1e18  # from Hub return value
lp_value_pls = lp_gibs * gibs_price_pls * 2  # both sides
net_pls = sell_revenue_pls - mint_cost_pls  # cash P&L (LP is locked value)
cumulative_pls += net_pls
print(f"  P&L: sell={sell_revenue_pls:.0f} - mint={mint_cost_pls:.0f} = {net_pls:+.0f} PLS  (cumulative: {cumulative_pls:+.0f})")
```

- [ ] **Step 4: Test — run 5 cycles, verify each triggers arb**

```bash
python3 -m scripts.Joystick.bot --pump
```

Verify:
- Each cycle: 1 TX (atomic via Hub)
- Gas: ~300 PLS (vs previous ~3,000 PLS)
- Arb detection rate: >50% (up from 8%)
- P&L: trending positive (spread > gas)

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/bot.py scripts/Joystick/engines/dss.py
git commit -m "feat(e2): balanced spread engine — impact-sized sells, arb-trigger guaranteed, P&L tracked"
```

---

### Task 6: Run tests and verify

**Files:**
- Test: `scripts/Joystick/tests/unit/` (existing probe tests)
- Test: `scripts/Joystick/tests/test_ladder.py` (existing ladder tests)

- [ ] **Step 1: Run all unit tests**

```bash
python3 -m pytest scripts/Joystick/tests/unit/ -q --tb=short
```

Expected: all pass (probe changes are backward-compatible).

- [ ] **Step 2: Run ladder tests**

```bash
python3 -m pytest scripts/Joystick/tests/test_ladder.py -v --tb=short
```

Expected: all pass (oracle changes are additive).

- [ ] **Step 3: Commit test verification**

```bash
git commit --allow-empty -m "test: all unit + ladder tests pass with HarvestV3 + probe pair-awareness"
```
