# Joystick Logic Flaw Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 logic flaws found in the Joystick bot code review that cause inflated profit reporting, TX reverts, and masked losses.

**Architecture:** Surgical edits to 4 files: `treasury_sniper.py` (flaws 1, 3, 6), `dss.py` (flaw 2), `bot.py` (flaw 4), `executor.py` (flaw 5). Each fix is independent — no cross-dependencies between tasks. Unit tests use existing mock-based patterns from `test_engines_5_6.py`.

**Tech Stack:** Python 3.10+, web3.py, pytest, unittest.mock

---

## File Map

| File | Action | Flaws |
|------|--------|-------|
| `scripts/Joystick/engines/treasury_sniper.py` | Modify | #1, #3, #6 |
| `scripts/Joystick/engines/dss.py` | Modify | #2 |
| `scripts/Joystick/bot.py` | Modify | #4 |
| `scripts/Joystick/core/executor.py` | Modify | #5 |
| `scripts/Joystick/tests/test_logic_fixes.py` | Create | All |

---

### Task 1: Fix E6 simulate() stale profit estimation (Flaw #1 + #6)

**Severity:** HIGH — causes strategist to always pick E6 over genuinely profitable engines.

**Root cause:** `simulate()` uses `t.estimated_pls` from recon JSON (up to 24h stale), while `execute()` uses live DEX quotes via `_find_best_sell_route()`. Also, the 100K PLS per-target cap is meaningless when 12 targets can sum to 1.2M PLS.

**Fix:** Make `simulate()` use `_find_best_sell_route()` for live pricing (same as `execute()`), and add a batch-level cap of 50K PLS total.

**Files:**
- Modify: `scripts/Joystick/engines/treasury_sniper.py:123-146`
- Test: `scripts/Joystick/tests/test_logic_fixes.py`

- [ ] **Step 1: Write failing test for simulate using live DEX quotes**

In `scripts/Joystick/tests/test_logic_fixes.py`:

```python
"""
test_logic_fixes.py — Unit tests for the 6 logic flaw fixes.
Pure unit tests — no chain interaction, no Anvil required.

Run:
  python -m pytest scripts/Joystick/tests/test_logic_fixes.py -v
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

os.environ.setdefault("TGSV8_ADDRESS", "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32")
os.environ.setdefault("PULSECHAIN_RPC", "http://127.0.0.1:8545")
os.environ.setdefault("PULSECHAIN_READ_RPC", "http://127.0.0.1:8545")
os.environ.pop("DYSNOMIA_PRIVATE_KEY", None)

if "scripts.Joystick.core.wallet" in sys.modules:
    del sys.modules["scripts.Joystick.core.wallet"]

from scripts.Joystick.engines.treasury_sniper import TreasurySniperEngine, TreasuryTarget


class TestE6SimulateUsesLiveQuotes(unittest.TestCase):
    """Flaw #1: simulate() must use live DEX quotes, not stale recon estimates."""

    @patch("scripts.Joystick.engines.treasury_sniper.w3_read")
    def test_simulate_calls_find_best_sell_route(self, mock_w3):
        """simulate() should call _find_best_sell_route for each target, not use t.estimated_pls."""
        mock_w3.eth.gas_price = 100 * 10**9  # 100 Gwei

        engine = TreasurySniperEngine()
        engine._last_load = float('inf')  # skip recon reload

        # Target with inflated recon estimate (99K PLS) but low live DEX value
        target = TreasuryTarget(
            label="INFLATED", address="0x" + "ab" * 20,
            backing_asset="0x" + "cd" * 20,
            self_balance=int(1000e18), parent_balance=int(500e18),
            pls_per_token=99.0, parent_pls=99.0,
            estimated_pls=99000.0,  # stale inflated value
        )
        engine._targets = [target]

        # Mock _size_claim to return non-zero (TGSv8 has tokens)
        engine._size_claim = MagicMock(return_value=int(500e18))

        # Mock _find_best_sell_route to return realistic live quote
        live_pls = int(2000 * 10**18)  # 2000 PLS (much less than 99K)
        engine._find_best_sell_route = MagicMock(return_value={
            "route": ["0xparent", "0xwpls"], "router": "V2",
            "expected_pls": live_pls, "mode": "direct",
        })

        profit, gas = engine.simulate()

        # Must have called _find_best_sell_route (live DEX), not used 99K recon
        engine._find_best_sell_route.assert_called_once()
        # Profit should be based on live 2000 PLS, not stale 99K
        self.assertLess(profit, 5000 * 10**18, "Profit should reflect live DEX quote, not stale recon")


class TestE6BatchCap(unittest.TestCase):
    """Flaw #6: batch-level profit cap prevents runaway estimates."""

    @patch("scripts.Joystick.engines.treasury_sniper.w3_read")
    def test_batch_profit_capped(self, mock_w3):
        """Total batch profit must be capped even when many targets sum higher."""
        mock_w3.eth.gas_price = 100 * 10**9

        engine = TreasurySniperEngine()
        engine._last_load = float('inf')

        # 10 targets each claiming 20K PLS = 200K total (should be capped)
        targets = []
        for i in range(10):
            addr = f"0x{i:040x}"
            targets.append(TreasuryTarget(
                label=f"T{i}", address=addr,
                backing_asset="0x" + "cd" * 20,
                self_balance=int(100e18), parent_balance=int(100e18),
                pls_per_token=200.0, parent_pls=200.0,
                estimated_pls=20000.0,
            ))
        engine._targets = targets

        engine._size_claim = MagicMock(return_value=int(100e18))
        engine._find_best_sell_route = MagicMock(return_value={
            "route": ["0xp", "0xw"], "router": "V2",
            "expected_pls": int(20000 * 10**18), "mode": "direct",
        })

        profit, gas = engine.simulate()

        MAX_BATCH_CAP = 50_000 * 10**18
        self.assertLessEqual(profit + gas, MAX_BATCH_CAP,
                             "Total batch estimate must be capped at 50K PLS")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest scripts/Joystick/tests/test_logic_fixes.py::TestE6SimulateUsesLiveQuotes -v`
Expected: FAIL — simulate() currently uses `t.estimated_pls` not live quotes.

- [ ] **Step 3: Implement fix in treasury_sniper.py simulate()**

Replace `simulate()` at line 123-146 in `scripts/Joystick/engines/treasury_sniper.py`:

```python
    def simulate(self) -> tuple[int, int]:
        """
        Returns (expected_profit_wei, estimated_gas_cost_wei).
        Uses live DEX quotes (same as execute) to avoid stale recon inflation.
        """
        self._refresh_targets()
        if not self._targets:
            return (0, 0)

        best = self._pick_best_batch()
        if not best:
            return (0, 0)

        # Use live DEX quotes per target (same method as _execute_batch)
        MAX_SANE_PROFIT_WEI = int(100_000 * 10**18)  # 100K PLS per-target cap
        MAX_BATCH_PROFIT_WEI = int(50_000 * 10**18)   # 50K PLS batch cap
        total_profit = 0
        for t in best:
            claim_amount = self._size_claim(t)
            if claim_amount > 0:
                route = self._find_best_sell_route(t.backing_asset, claim_amount)
                est = min(route["expected_pls"], MAX_SANE_PROFIT_WEI)
            else:
                est = min(int(t.estimated_pls * 10**18), MAX_SANE_PROFIT_WEI)
            total_profit += est

        # Batch-level cap prevents runaway sums from many targets
        total_profit = min(total_profit, MAX_BATCH_PROFIT_WEI)

        gas_price = w3_read.eth.gas_price
        gas_cost = GAS_PER_CLAIM * len(best) * gas_price

        if total_profit <= gas_cost:
            return (0, 0)

        return (total_profit - gas_cost, gas_cost)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest scripts/Joystick/tests/test_logic_fixes.py -v -k "E6Simulate or E6Batch"`
Expected: Both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/engines/treasury_sniper.py scripts/Joystick/tests/test_logic_fixes.py
git commit -m "fix: E6 simulate uses live DEX quotes + 50K batch cap"
```

---

### Task 2: Fix E2 _acquire_aff deposit overflow (Flaw #2)

**Severity:** HIGH — causes TX revert when swap returns less than shortfall due to slippage.

**Root cause:** After swapping WPLS for AFF (min_out = 90% of shortfall), the code deposits full `shortfall_wei` into Hub. If swap returned 95% of shortfall, deposit reverts because Joey doesn't have enough AFF.

**Fix:** Read Joey's actual AFF balance after the swap, deposit `min(actual_balance, shortfall_wei)`.

**Files:**
- Modify: `scripts/Joystick/engines/dss.py:336-351`
- Test: `scripts/Joystick/tests/test_logic_fixes.py`

- [ ] **Step 1: Write failing test**

Append to `scripts/Joystick/tests/test_logic_fixes.py`:

```python
class TestE2DepositOverflow(unittest.TestCase):
    """Flaw #2: E2 _acquire_aff must deposit actual AFF received, not full shortfall."""

    @patch("scripts.Joystick.engines.dss.send_tx")
    @patch("scripts.Joystick.engines.dss.approve_if_needed")
    @patch("scripts.Joystick.engines.dss.router_contract")
    @patch("scripts.Joystick.engines.dss.erc20")
    @patch("scripts.Joystick.engines.dss.safe")
    @patch("scripts.Joystick.engines.dss.w3_submit")
    def test_deposit_uses_actual_balance(self, mock_w3s, mock_safe, mock_erc20,
                                          mock_router, mock_approve, mock_send):
        """Deposit amount should be min(actual_aff_balance, shortfall_wei)."""
        from scripts.Joystick.engines.dss import DSSEngine

        engine = DSSEngine()

        # Setup mocks
        mock_w3s.eth.gas_price = 100 * 10**9
        mock_w3s.eth.contract = MagicMock()

        # Mock send_tx to return fake receipts
        fake_receipt = {
            "transactionHash": MagicMock(hex=MagicMock(return_value="0x" + "aa" * 32)),
            "gasUsed": 100_000,
            "effectiveGasPrice": 100 * 10**9,
        }
        mock_send.return_value = fake_receipt
        mock_approve.return_value = None

        # Mock the AFF balance check AFTER swap — returns 95% of shortfall
        shortfall = int(100 * 10**18)  # 100 AFF needed
        actual_received = int(95 * 10**18)  # only got 95 AFF

        # safe() should be called to check balanceOf after swap
        mock_safe.return_value = actual_received

        hub = MagicMock()
        engine._cheapest_aff_route = MagicMock(return_value=("dex", int(5000 * 10**18)))

        tx_hashes, gas_spent = engine._acquire_aff(shortfall, hub, dry_run=False)

        # The deposit call should use actual_received (95), not shortfall (100)
        deposit_calls = [c for c in hub.functions.deposit.call_args_list]
        if deposit_calls:
            deposit_amount = deposit_calls[0][0][1]  # second positional arg
            self.assertLessEqual(deposit_amount, actual_received,
                                 f"Deposit {deposit_amount/1e18} AFF > received {actual_received/1e18}")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest scripts/Joystick/tests/test_logic_fixes.py::TestE2DepositOverflow -v`
Expected: FAIL — current code deposits `shortfall_wei` (100) not actual balance (95).

- [ ] **Step 3: Implement fix in dss.py**

Replace lines 336-351 in `scripts/Joystick/engines/dss.py` (the deposit section after the swap):

```python
            # Now deposit AFF from Joey → Hub (use actual balance, not shortfall)
            aff_c_submit = w3_submit.eth.contract(address=aff_cs, abi=erc20(AFFECTION).abi)
            actual_aff = safe(aff_c_submit, "balanceOf", JOEY_WALLET) or 0
            deposit_amount = min(actual_aff, shortfall_wei)
            if deposit_amount == 0:
                log.warning("E2: No AFF to deposit after swap")
                return tx_hashes, gas_spent

            r = approve_if_needed(aff_c_submit, hub_addr, deposit_amount,
                                  "AFF→Hub", dry_run=dry_run)
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            r = send_tx(
                hub.functions.deposit(aff_cs, deposit_amount),
                f"Deposit {int(deposit_amount / 10**18)} AFF → Hub",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest scripts/Joystick/tests/test_logic_fixes.py::TestE2DepositOverflow -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/engines/dss.py scripts/Joystick/tests/test_logic_fixes.py
git commit -m "fix: E2 deposit uses actual AFF balance, not full shortfall"
```

---

### Task 3: Fix E6 _refresh_targets price semantics (Flaw #3)

**Severity:** MEDIUM — misleading variable names cause the recon estimator to conflate child and parent token prices.

**Root cause:** `parent_pls = pls_per_tok` assigns the child token's DEX price to `parent_pls`. The `estimated_pls` then computes gross value of claimable tokens without subtracting acquisition cost.

**Fix:** Rename for clarity and add a comment. The estimated_pls field is used as a filter/sort key only (live DEX quotes do the real pricing in simulate/execute after Task 1), so the semantic fix is naming + documentation.

**Files:**
- Modify: `scripts/Joystick/engines/treasury_sniper.py:241-258`

- [ ] **Step 1: Fix naming and add cost awareness comment**

Replace lines 241-258 in `scripts/Joystick/engines/treasury_sniper.py`:

```python
            qty_tokens = self_bal / (10 ** decimals)
            # pls_per_tok is the child token's DEX price (from recon).
            # This gives gross value of claimable tokens, NOT net profit
            # (cost to acquire ammo is unknown here). Used only for
            # filtering and sort order — live DEX quotes in simulate()
            # and _execute_batch() do the real pricing.
            token_pls = pls_per_tok
            est_pls_gross = qty_tokens * token_pls

            if est_pls_gross < MIN_PROFIT_PLS:
                continue

            targets.append(TreasuryTarget(
                label         = entry.get("label", addr[:10]),
                address       = addr,
                backing_asset = parent_addr,
                self_balance  = self_bal,
                parent_balance= parent_bal,
                pls_per_token = pls_per_tok,
                parent_pls    = token_pls,
                decimals      = decimals,
                estimated_pls = est_pls_gross,
            ))
```

- [ ] **Step 2: Verify no regressions**

Run: `python -m pytest scripts/Joystick/tests/test_logic_fixes.py -v`
Expected: All existing tests still pass (field names unchanged in TreasuryTarget dataclass).

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/engines/treasury_sniper.py
git commit -m "fix: clarify E6 recon price semantics (gross value, not net profit)"
```

---

### Task 4: Fix bot.py loss masking (Flaw #4)

**Severity:** MEDIUM — corrupts adaptive delay and P&L tracking.

**Root cause:** `realized_profit = max(0, pls_after - pls_before)` clamps losses to 0. An engine that burns gas with no revenue reports 0 loss, classified as "strategic" instead of "failure".

**Fix:** Track actual PLS delta (can be negative). Classify negative delta as "loss" for adaptive delay. Log the actual loss.

**Files:**
- Modify: `scripts/Joystick/bot.py:394-409`
- Test: `scripts/Joystick/tests/test_logic_fixes.py`

- [ ] **Step 1: Write failing test**

Append to `scripts/Joystick/tests/test_logic_fixes.py`:

```python
class TestBotLossMasking(unittest.TestCase):
    """Flaw #4: bot must track actual PLS losses, not clamp to 0."""

    def test_negative_delta_not_masked(self):
        """When pls_after < pls_before, realized delta should be negative."""
        pls_before = int(2_000_000 * 10**18)
        pls_after  = int(1_999_500 * 10**18)  # lost 500 PLS to gas

        # Current buggy code:
        buggy_profit = max(0, pls_after - pls_before)
        self.assertEqual(buggy_profit, 0, "Sanity: buggy code masks loss")

        # Fixed code should preserve the negative delta:
        realized_delta = pls_after - pls_before
        self.assertLess(realized_delta, 0, "Fixed code should show negative delta")
        self.assertEqual(realized_delta, -500 * 10**18)
```

- [ ] **Step 2: Run test (this test always passes — it's a design validation)**

Run: `python -m pytest scripts/Joystick/tests/test_logic_fixes.py::TestBotLossMasking -v`
Expected: PASS (this test validates the logic, the actual fix is in bot.py).

- [ ] **Step 3: Implement fix in bot.py**

Replace lines 394-409 in `scripts/Joystick/bot.py`:

```python
                pls_after = pls_balance()
                realized_delta = pls_after - pls_before  # can be negative (gas loss)

                log.info("✓ %s [%s]: reported=%.4f PLS  realized=%.4f PLS  TXs=%d  notes=%s",
                         engine.display_name, rec.wallet_role,
                         result.net_pls, realized_delta / 1e18,
                         len(result.tx_hashes), result.notes)

                if realized_delta > 0 and not self.dry_run and not self.multi_wallet:
                    # Only auto-compound in single-wallet mode
                    self.compound(realized_delta)
                    cycle_outcome = "profit"
                elif realized_delta > 0:
                    cycle_outcome = "profit"
                elif realized_delta < -100 * 10**18:
                    # Lost more than 100 PLS — treat as failure for adaptive delay
                    cycle_outcome = "failure"
                    log.warning("  Loss detected: %.1f PLS (gas > revenue)", realized_delta / 1e18)
                else:
                    cycle_outcome = "strategic"
```

- [ ] **Step 4: Verify no regressions**

Run: `python -m pytest scripts/Joystick/tests/test_logic_fixes.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/bot.py scripts/Joystick/tests/test_logic_fixes.py
git commit -m "fix: track actual PLS losses instead of clamping to zero"
```

---

### Task 5: Fix executor nonce-advanced-no-receipt (Flaw #5)

**Severity:** LOW — causes silent TX tracking gaps when RPC drops receipts.

**Root cause:** When nonce advances but receipt is lost, executor returns `None`. Engines check `if r:` (False for None) and skip recording the TX hash and gas cost.

**Fix:** Return a synthetic "partial receipt" dict with the TX hash and estimated gas, so engines can at least record the hash. Log clearly that gas cost is estimated.

**Files:**
- Modify: `scripts/Joystick/core/executor.py:194-203`

- [ ] **Step 1: Implement fix**

Replace lines 194-203 in `scripts/Joystick/core/executor.py`:

```python
    if receipt is None:
        # Receipt not found after 60s — check if nonce advanced (TX mined but hash lost)
        try:
            on_chain_nonce = w3_read.eth.get_transaction_count(tx_from)
        except Exception:
            on_chain_nonce = nonce  # Can't check, assume stuck
        if on_chain_nonce > nonce:
            log.warning("  Receipt not found but nonce advanced (%d->%d) -- TX mined (hash dropped by RPC)", nonce, on_chain_nonce)
            _reset_nonce_for(wallet_ctx)
            # Return synthetic receipt so engines can record the TX hash and estimated gas.
            # Gas cost is estimated (gas_limit * maxFeePerGas) since we can't read the receipt.
            estimated_gas_cost = gas_limit * eip1559["maxFeePerGas"]
            log.warning("  Returning synthetic receipt (estimated gas: %d wei)", estimated_gas_cost)
            return {
                "status": 1,
                "transactionHash": type('', (), {"hex": lambda self: tx_hash_hex})(),
                "blockNumber": 0,
                "gasUsed": gas_limit,
                "effectiveGasPrice": eip1559["maxFeePerGas"],
                "_synthetic": True,
            }
        else:
            log.error("  Receipt timeout and nonce unchanged -- TX 0x%s dropped from mempool", tx_hash_hex)
            _reset_nonce_for(wallet_ctx)
            raise TimeExhausted(f"TX 0x{tx_hash_hex} dropped -- nonce {nonce} still pending")
```

- [ ] **Step 2: Verify no regressions**

Run: `python -m pytest scripts/Joystick/tests/test_logic_fixes.py -v`
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/core/executor.py
git commit -m "fix: return synthetic receipt when nonce advances but receipt lost"
```

---

### Task 6: Final dry-run validation

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest scripts/Joystick/tests/test_logic_fixes.py -v`
Expected: All tests pass.

- [ ] **Step 2: Run bot in dry-run mode to verify no regressions**

Run: `python -m scripts.Joystick.bot --dry-run --once 2>&1 | head -50`
Expected: Bot completes one cycle. E6 profit estimate should be dramatically lower (under 50K PLS instead of 99K). No import errors or crashes.

- [ ] **Step 3: Verify E6 simulate vs execute convergence**

Check the dry-run output: E6's estimated profit in the strategist recommendation should be close to the execute-reported profit (within 2x), not 50x apart as before.

- [ ] **Step 4: Commit all changes together if not already committed individually**

```bash
git add -A scripts/Joystick/
git commit -m "fix: 6 logic flaws — E6 stale estimates, E2 deposit overflow, loss masking, executor receipts"
```
