# Joystick VPS Polish Report

**Date**: 2026-03-18
**Trigger**: Post-dry-run polish (1h46m VPS dry-run passed)
**Scope**: Console output quality, sim timeout fixes, gas label corrections

---

## 1. Console Logging Overhaul

### 1a. Timestamp Removal
- Console formatter changed from `"%(asctime)s %(name)-12s %(levelname)-8s %(message)s"` to `"%(name)-16s %(levelname)-8s %(message)s"`
- journald provides timestamps; removing Python-level timestamps eliminates redundancy
- File handler retains timestamps with `datefmt="%Y-%m-%d %H:%M:%S"`

### 1b. Short Logger Names
- Created `core/log_names.py` with centralized `_NAME_MAP` (35 entries)
- All 30+ modules converted from `logging.getLogger(__name__)` to `get_logger(__name__)`
- Logger names now display as: `bot`, `core.exec`, `E1.razor`, `E2.cereal`, etc.
- Remaining: `tests/anvil_helpers.py` (test code, left as-is)

### 1c. Emoji Prefixes

| Emoji | Context | File(s) |
|-------|---------|---------|
| 💰 | Balance line | bot.py |
| ⛽ | Gas price / gas line | bot.py, executor.py, gas_oracle.py |
| 📉 | Gas falling advisory | bot.py |
| 🧠 | Strategist skip | bot.py |
| ✅/❌ | Cycle result | bot.py |
| 🧹 | Sweep | bot.py |
| 🔄 | Loop result / graph rebuild | bot.py, pair_discovery.py |
| 😴 | Sleep | bot.py |
| 🚀 | Startup | bot.py |
| 📤 | TX send | executor.py |
| 📦 | TX receipt OK | executor.py |
| ⏰ | Sim timeout | concurrency.py |
| ⚠️ | Sim error / loop failure | concurrency.py, bot.py |
| 🔴 | Circuit breaker trip | rpc_provider.py |
| 🟢 | Circuit breaker recovery | rpc_provider.py |
| 🔌 | RPC retries exhausted | rpc_provider.py |
| 🎯 | Arb top result | arb.py |
| 📊 | Pair discovery counts | pair_discovery.py |
| 💾 | Pair cache hit | pair_discovery.py |
| 🚨 | Gas low warning | gas_guard.py |
| ⏭️ | Auto-skip | strategist.py |
| 👛 | Wallet loaded | wallet_manager.py |
| 🏜️ | Wallet not configured | wallet_manager.py |
| 👤 | Single-wallet mode | wallet_manager.py |

### 1d. Number Formatting
- `fmt_pls(wei)` → comma-separated PLS with 4 decimals (e.g., `1,979,624.6000`)
- `fmt_int(n)` → comma-separated integer (e.g., `854,232`)
- `fmt_pls_short(float)` → comma-separated PLS with 2 decimals (e.g., `1,979.62`)
- Applied in: bot.py (balance, gas, cycle results), executor.py (gas line)

### 1e. Gwei → Beats
Fixed all active log output and comments across:
- `bot.py` — gas log line, GasTooHigh exception
- `executor.py` — gas log line
- `gas_oracle.py` — debug log, status dict keys (`current_beats`, `average_beats`, `ceiling_beats`, `window_max_beats`, `window_min_beats`), `__repr__`
- `config.py` — comment on GAS_PRICE_CEIL
- `phreak.py`, `treasury_sniper.py`, `spine_runner.py` — gas-too-high notes
- `terraform.py` — comment

**Not changed** (tools/tests/archive — not bot runtime output):
- `tools/tgsv8_recon.py`, `tools/tgsv8_mint_test.py`, `tools/tgsv8_mint_wm_test.py`
- `tests/test_razor_pulsechain.py`
- `tools/archive/` files
- `engines/lau.py` comments/docstrings (informational, not log output)
- `oracle/graph.py` CLI print (not bot runtime)

---

## 2. Terraform Loop Disabled

- `bot.py`: `self.loops = []` with comment explaining CHOA.Chat ABI mismatch
- `loops/terraform.py`: Added disabled warning in docstring header
- Code preserved for future re-enablement when correct ABI is confirmed

---

## 3. Arb + TokenFactory Sim Timeout Fix

### 3a. Prevent discover_pairs() Inside Sim (CRITICAL)
- `arb.py:_simulate_cross_pair()`: Removed direct `discover_pairs()` call
- If no cache exists, sets `self._needs_graph_rebuild = True` and returns `None` (skips Mode 3)
- If cache exists but reserves are stale, calls `refresh_reserves()` (fast: ~1s Multicall3)

### 3b. Background Graph Rebuild
- `bot.py`: Between cycle steps, checks `arb_engine._needs_graph_rebuild`
- Runs `discover_pairs()` outside sim timeout window
- Logs result with pair/token counts

### 3c. TokenFactory Check
- `token_factory.py` does NOT use `discover_pairs()` — uses `oracle/price.py` for DEX quotes
- No timeout risk — no fix needed

### 3e. Per-Engine Sim Timeouts
- `concurrency.py`: Added `SIM_TIMEOUT_MAP` with per-engine overrides
- Arb: 15s (graph operations), TokenFactory: 10s (multi-route pricing), Default: 5s

---

## 4. Functionality Audit

### Files Changed (17 total)
| File | Changes |
|------|---------|
| `bot.py` | Console formatter, logger, emojis, number formatting, Beats labels, terraform disabled, background graph rebuild |
| `core/log_names.py` | **NEW** — centralized logger name registry + fmt helpers |
| `core/concurrency.py` | Per-engine sim timeouts, emoji warnings |
| `core/executor.py` | Emoji prefixes, Beats labels |
| `core/rpc_provider.py` | Emoji prefixes (circuit breaker, recovery, exhausted) |
| `core/gas_oracle.py` | Beats labels (methods, status keys, repr, comments) |
| `core/gas_guard.py` | Emoji on gas-low warning |
| `core/config.py` | Beats in comment |
| `core/strategist.py` | Auto-skip emoji |
| `core/wallet_manager.py` | Wallet status emojis (👛, 🏜️, 👤) |
| `oracle/pair_discovery.py` | Cache/discovery emojis |
| `engines/arb.py` | Sim timeout fix, top-result emoji, `_needs_graph_rebuild` flag |
| `engines/phreak.py` | Beats in gas-too-high note |
| `engines/treasury_sniper.py` | Beats in gas-too-high note |
| `engines/spine_runner.py` | Beats in gas-too-high note |
| `loops/terraform.py` | Disabled header, Beats in comment |
| 30+ files | `getLogger(__name__)` → `get_logger(__name__)` |

### Files NOT Changed (as specified)
- `core/chain.py` — infrastructure, no user-facing logs needing polish
- `core/simulator.py` — minimal logging, no changes needed
- `core/wallet.py` — legacy module, minimal logging
- `core/sell_queue.py` — minimal logging
- `core/event_logger.py` — structured JSON output, not console
- `oracle/price.py` — no user-facing logs
- `oracle/scanner.py` — minimal logging
- `oracle/profitability.py` — no logging
- `engines/dss.py` — minimal logging
- `engines/beat.py` — minimal logging
- `tools/` — standalone tools, not bot runtime
- `tests/` — test code
- `data/` — data files

---

## 5. Remaining TODOs

| Priority | Item | Notes |
|----------|------|-------|
| LOW | `engines/lau.py` comments still say "Gwei" | Informational only, not log output |
| LOW | `oracle/graph.py` CLI `__main__` prints "Gwei" | CLI tool, not bot runtime |
| LOW | `tools/*.py` print "Gwei" | Standalone tools, not bot runtime |
| NONE | `gas_oracle.py` backward-compat aliases | `current_gwei`/`average_gwei` kept as aliases for `current_beats`/`average_beats` |

---

## 6. Expected Console Output (Post-Polish)

```
bot              INFO     🚀 Joystick V2 starting (dry_run=False)
bot              INFO     💰 PLS: 1,979,625 | GIBS: 0.0000 | AFF: 127.18
bot              INFO     ⛽ Gas: 741,000 Beats (avg=738,000, trend=stable, ceil=2,000,000)
core.sim         INFO     Parallel sim: 6/8 engines in 287ms (3 OK)
bot              INFO     🧠 Strategist: Joey=E3 MERIDIAN, Minter=E8 PHR3AK, Seller=skip
bot              INFO     ✅ E3 MERIDIAN: profit 0.00 PLS | gas 1,469.23 PLS | net -1,469.23 PLS
bot              INFO     ✅ E8 PHR3AK: profit 0.00 PLS | gas 234.50 PLS | net -234.50 PLS
bot              INFO     😴 Sleep 30s
```

Compared to pre-polish:
```
2026-03-17 14:22:01 joystick     INFO     Joystick V2 starting (dry_run=False)
2026-03-17 14:22:01 joystick     INFO     PLS: 1979624.6  GIBS: 0.0  AFF: 127.18
2026-03-17 14:22:01 joystick     INFO     Gas: 741000 Gwei (avg=738000, trend=stable, ceil=2000000)
...
2026-03-17 14:22:02 joystick     INFO     [Time '14:22:02' Date '2026-03-17'] E3 MERIDIAN: profit 0.0000 PLS | gas 1469.2300 PLS | net -1469.2300 PLS
```

Key improvements:
- No redundant timestamps (journald provides them)
- Short logger names (16-char column)
- Emoji prefixes for visual scanning
- Comma-formatted numbers
- "Beats" not "Gwei"
- No `[Time/Date]` block in result lines
