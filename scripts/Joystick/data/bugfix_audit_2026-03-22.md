# Joystick Bug Audit — 2026-03-22

Systematic codebase audit: core → engines → oracle → bot orchestrator.
All 55+ Python files reviewed. 14 files modified.

## HIGH Severity (Fixed)

### 1. sell_queue.py:83 — V2 router used V1 address
**Bug**: `("V2", PULSEX_V1_ROUTER)` — V2 price check returned V1 quotes.
**Fix**: Changed to `("V2", PULSEX_V2_ROUTER)` + imported `PULSEX_V2_ROUTER`.
**Impact**: SellQueue could miss better V2 pricing or sell on wrong DEX.

### 2. route_auditor.py:41-49 — Wrong pDAI and pUSDC addresses
**Bug**: Hardcoded `0xefD766...` (pDAI) and `0x015D38...` (pUSDC) — not the canonical addresses.
**Fix**: Import `PDAI`/`PUSDC` from `config.py` (canonical `0x6B175...` and `0xA0b869...`).
**Impact**: Payment route audit checked wrong tokens, marking routes as funded/unfunded incorrectly.

### 3. spine_runner.py:233,152,365 — pls_expected overflow (10^18 too large)
**Bug**: `pls_per_child = pls_ptok * 1e18` baked 1e18 into the price. Then `pls_expected = child_out_wei * pls_per_child` produced a number 10^18 too large, causing false profitability signals.
**Fix**: Store `pls_per_child` as raw float (PLS per token). Formula `child_out_wei * pls_per_child` naturally produces wei when decimals=18.
**Impact**: SpineRunner would report astronomical fake profits, potentially triggering unprofitable transactions.

### 4. treasury_sniper.py:203,242 — est_pls divided by 1e18 for no reason
**Bug**: `est_pls = qty_tokens * parent_pls / 1e18` — both inputs are human-readable floats, so `/1e18` makes the estimate 10^18 too small. All targets filtered as unprofitable.
**Fix**: Removed spurious `/1e18` division. Also cast `gas_cost_wei` to `int()` (was float from `GAS_MULT`).
**Impact**: TreasurySniper would never find any profitable targets.

### 5. executor.py:107-113 — Multi-wallet nonce tracking
**Bug**: When `wallet_ctx` was provided (Minter/Seller), code fell through to `wallet.next_nonce()` which tracks Joey's nonce — producing wrong nonces for other wallets.
**Fix**: Added `nonce_tracker` field to `WalletConfig` dataclass. `WalletManager` now wires nonce trackers into configs at creation. Executor uses `wallet_ctx.nonce_tracker.next()` when available.
**Impact**: All Minter/Seller transactions would use Joey's nonce and fail.

### 6. gas_guard.py:77,106 — Emergency refill used V1 router for V2-only GIBS pair
**Bug**: `router_contract()` defaults to V1, but GIBS/WPLS is a V2 pair. Emergency refill would fail to find the pair.
**Fix**: Use V2 router for GIBS sell. AFF fallback tries V2 first, falls back to V1.
**Impact**: Emergency PLS refill would fail when gas runs low, potentially bricking the bot.

## MEDIUM Severity (Fixed)

### 7. scanner.py:100 — Malformed zero-address check
**Bug**: `"0x" * 21` evaluates to `"0x0x0x..."` (not a valid address). Should be `"0x" + "0" * 40`.
**Fix**: Changed to `"0x" + "0" * 40`.

### 8. scanner.py:67 — Non-atomic cache write
**Bug**: Direct `open(CACHE_FILE, "w")` → crash mid-write corrupts cache.
**Fix**: Write to `.tmp` then `os.replace()` with cleanup on failure.

### 9. beat.py:107 — Gas cost over-estimated by 30%
**Bug**: `gas_cost_wei = gas_est * gas_price * 1.3` — the 1.3x multiplier is for gas LIMIT (safety buffer), not gas COST estimation. Over-estimates cost by 30%, causing Beat to be skipped prematurely.
**Fix**: Removed 1.3x from cost calc: `gas_cost_wei = gas_est * gas_price`.

### 10. bot.py:460-461 — Compound swap with amountOutMin=1
**Bug**: No slippage protection on PLS→AFF compound swap. MEV bots could sandwich.
**Fix**: Quote expected output via `get_amounts_out()`, apply `MAX_SLIPPAGE` tolerance.

### 11. pair_discovery.py:427 — Non-atomic cache write
**Bug**: `save_pair_graph()` wrote directly to file without temp+rename.
**Fix**: Write to `.tmp` then `os.replace()`.

### 12. profitability.py:104 — payment_pls==0 false positive
**Bug**: When `payment_pls=0` (no DEX liquidity for payment token), `net_profit = dex_out - 0 - gas` shows false profitability.
**Fix**: Return unprofitable result when `payment_pls=0 and payment_cost>0`.

## LOW Severity (Fixed)

### 13. config.py:122 — Duplicate PULSEX_V2_ROUTER definition
Removed duplicate (identical to line 87).

### 14. profitability.py:14-18 — Dead imports
Removed unused `Decimal`, `getcontext()`, `w3_read`.

### 15. graph.py:30 — Unused `math` import
Removed.

### 16. pair_discovery.py:205-206 — Dead variables
Removed unused `a_bytes`, `b_bytes` in `_encode_get_pair()`.

### 17. Engine docstring numbering mismatches
- beat.py: "Engine 4" → "Engine 3 (MERIDIAN)"
- lau.py: "Engine 6" → "Engine 5 (ABUPRU)"
- spine_runner.py: "Engine 6" → "Engine 7 (BACKBONE)" + all log prefixes E6→E7
- treasury_sniper.py: "Engine 5" → "Engine 6 (DaVINCI)" + all log prefixes E5→E6

## Files Modified (14)

| File | Changes |
|------|---------|
| `core/sell_queue.py` | V2 router fix |
| `core/executor.py` | Multi-wallet nonce tracking |
| `core/wallet_manager.py` | Added nonce_tracker to WalletConfig |
| `core/config.py` | Removed duplicate PULSEX_V2_ROUTER |
| `core/gas_guard.py` | V2 router for GIBS, V2/V1 fallback for AFF |
| `oracle/route_auditor.py` | Canonical pDAI/pUSDC addresses |
| `oracle/scanner.py` | Zero-address fix + atomic write |
| `oracle/profitability.py` | payment_pls=0 guard + dead imports |
| `oracle/pair_discovery.py` | Atomic write + dead vars |
| `oracle/graph.py` | Dead import |
| `engines/beat.py` | Gas cost fix + docstring |
| `engines/spine_runner.py` | pls_per_child overflow + docstrings |
| `engines/treasury_sniper.py` | est_pls fix + gas_cost_wei int cast + docstrings |
| `engines/lau.py` | Docstring |
| `bot.py` | Compound swap slippage protection |

## Verification

- All 14 files pass `py_compile`
- Full import chain verified (core → oracle → engines → bot)
- pDAI/pUSDC addresses match config.py canonical values
- WalletConfig.nonce_tracker field present
- V2 router correctly imported in sell_queue
- Dead imports confirmed removed
- Gas cost multiplier confirmed removed from beat estimate
