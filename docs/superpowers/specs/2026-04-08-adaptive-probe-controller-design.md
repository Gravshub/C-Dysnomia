# Adaptive Probe Controller — Design Spec

**Date**: 2026-04-08
**Status**: design complete, awaiting user review before plan + implementation
**Author**: Joey + Claude (interactive brainstorming)
**Scope**: GIBS/WPLS V2 pair only (controller is pair-agnostic internally; single instance for now)

---

## Problem statement

The Joystick bot's E2 CEREAL engine sells GIBS in fixed ~8 GIBS chunks (45% of a 17-GIBS mint cycle, the rest going to LP accumulation). Each sell creates ~0.29% price impact on the GIBS/WPLS pool. External arbitrage bots respond once every ~14-16 sells, when cumulative dislocation reaches ~4% — their effective trigger threshold.

Measured over 2000 blocks (~5 hours):

| Metric | Value |
|---|---|
| Joey sells | 113 (avg 8.25 GIBS) |
| External arb buys | 7 (avg ~60 GIBS) |
| Arb response ratio | 1 buy per 16 sells |
| Net GIBS pool drift | +519 GIBS (+9.04% of reserve) |
| GIBS price drift | 43.6 → 39.4 PLS (−9.6%) |

Without per-sell arbing, the pool slowly accumulates excess GIBS, GIBS price drifts down, and E2's lifespan is bounded by the price floor (`BREAK_EVEN_GIBS_PLS = 21.5` in `ladder_oracle.py`). At current drift rate, E2 would halt in ~20 hours from a healthy starting price.

The existing approach of statically sizing sells does not adapt to changing pool depth or external bot behavior. A naive fix (always sell bigger) wastes Joey's PLS in slippage. A naive fix (rebalance pool manually with addLiquidity) requires constant attention.

We want an automated mechanism that:

1. Finds the **smallest sell size** that reliably attracts an external arb response
2. Locks onto that "sweet spot" once found
3. Re-discovers a new sweet spot when conditions change
4. After each successful arb, restores the pool by adding LP sized to match the arb (creating a permanent floor without burning)
5. Stays bounded — never spends more PLS in slippage than configured limits allow

This document describes a standalone advisor module, the Adaptive Probe Controller, that provides this behavior to the existing E2 engine without changing E2's TX submission logic.

---

## Goals and non-goals

**Goals**:

- Automate the search for the minimum effective sell size on GIBS/WPLS
- Adapt continuously as pool depth and external bot behavior change
- After each successful arb, restore pool balance via Joey-funded LP add (matching the arb size)
- Bound worst-case slippage exposure with hard caps and time-based throttles
- Provide structured observability (logs, JSON-L events, snapshot API) without coupling to the dashboard
- Survive bot restarts cleanly (sweet spot persistence)

**Non-goals**:

- Multi-pair probing (this controller is single-pair; multiple instances would be a follow-up)
- Replacing E2's TX submission logic (controller is a pure advisor; E2 still owns the TXs)
- Estimating profit / P&L (the engine layer reports P&L; the controller only reports state)
- Dashboard integration (snapshot method exists but no route is defined here — follow-up)
- Detecting adversarial arb bots that might try to mislead the controller (out of scope)
- Probing on pairs other than GIBS/WPLS (every observed external arb routes through GIBS/WPLS as hop 1)
- Replacing E2's existing LADDER rescue path (rescue handles a different scenario — Hub WPLS drained — and stays in place)

---

## Architecture

### Module location

`scripts/Joystick/core/probe_controller.py`

Lives under `core/` (not `engines/` or `oracle/`) because it is infrastructure that engines consume, not an engine or a market data source.

### Public API

Five methods. The entire surface E2 sees:

```python
class ProbeController:
    def next_sell_gibs(
        self,
        hub_gibs_balance: int,
        pool_reserves: tuple[int, int],
    ) -> int:
        """Returns the GIBS amount (wei) E2 should sell this cycle.

        - Computes the size from the current state (PROBING/LOCKED/etc.)
        - Converts impact % to a concrete GIBS amount via constant-product math
        - Caps at hub_gibs_balance (prevents impossible sells)
        - Returns 0 if a previous sell is still within its monitoring window
        """

    def record_sell(
        self,
        sell_gibs_wei: int,
        block_number: int,
        tx_hash: str,
    ) -> None:
        """Called by E2 immediately after the sell TX mines.

        Stores PendingSell with deadline_block = block_number + 5.
        Block number MUST come from the receipt, not w3.eth.block_number.
        """

    def check_arb_response(self) -> ArbResponse:
        """Polls Swap events on GIBS/WPLS in the pending sell's window.

        Returns one of:
          - ArbResponse.PENDING — still within window, no arb seen yet
          - ArbResponse.ARB_DETECTED(gibs_size_wei, tx_hash, block, sender)
          - ArbResponse.NO_RESPONSE — window expired with no matching swap

        Side effect: advances state machine and updates last_arb_gibs.
        """

    def lp_add_target(self) -> Optional[int]:
        """If a recent arb succeeded, returns the GIBS amount to LP-add this cycle.

        Returns None if there's nothing pending. Called by E2 after the
        arb response check; if non-None, E2 executes a Hub.mintLPAndSell
        with lp_bps=10000 (LP-only) sized to match.
        """

    def status(self) -> dict:
        """Human-readable state snapshot for logs and (eventual) dashboard."""
```

`ArbResponse` is a small ADT-like dataclass with three variants. Implementation detail.

### Dependencies

- `core.chain.w3_read` — for `eth.get_logs` Swap event polling
- `core.chain.pair_contract` — for sanity-check reserves reads
- `core.event_logger.events` — for structured JSON-L events
- `core.config` — for constants and `GIBS_WPLS_V2_PAIR` address

### Deliberately NOT depending on

- `engines.dss` — E2 depends on the controller, not the other way around (no circular import)
- `core.strategist` — controller does not make strategic decisions, only sell-sizing ones
- Any dashboard module — controller is headless

### E2 integration (dss.py diff scope)

Minimal diff. The controller is instantiated once in `bot.py` and passed into `DSSEngine.__init__` as a dependency. Inside `_execute_harvest`:

1. Before the existing sell flow, call `probe.check_arb_response()` and act on PENDING / ARB_DETECTED / NO_RESPONSE
2. Call `probe.lp_add_target()`; if non-None, run a Hub LP-only TX to restore the pool
3. Call `probe.next_sell_gibs(hub_gibs_balance, current_reserves)` to determine sell size
4. Submit the existing sell pipeline with the controller's size
5. After mine, call `probe.record_sell(receipt.size, receipt.blockNumber, receipt.tx_hash)`

The `_execute_ladder` rescue path is **untouched**. The controller only takes over harvest-mode sell sizing.

---

## State machine

Five modes. All transitions are explicit and bounded.

```
                                ┌─────────────┐
                ┌──────────────►│   PROBING   │◄──────────────┐
                │               └──────┬──────┘               │
                │                      │                      │
                │                arb detected                 │
                │                      │                      │
                │                      ▼                      │
                │               ┌─────────────┐               │
                │               │   LOCKED    │               │
                │               └──────┬──────┘               │
                │                      │                      │
                │              2 consecutive                  │
                │              no-response cycles             │
                │                      │                      │
                │                      ▼                      │
                │              ┌──────────────┐               │
                │              │  RE_PROBING  │───────────────┤
                │              └──────────────┘   arb at      │
                │                                 lower %     │
                │                                             │
            probe_pct > MAX_IMPACT_PCT                        │
                │                                             │
                ▼                                             │
        ┌──────────────┐    after 3 blocks                    │
        │    CAPPED    │──────────────────────────────────────┘
        └──────┬───────┘
               │
        cap_loops ≥ 10
               │
               ▼
        ┌─────────────┐    after 30 blocks
        │   PAUSED    │─────────────────► (back to PROBING from baseline)
        └─────────────┘   cap_loops = 0
```

### State fields

```python
@dataclass
class ProbeState:
    mode: Literal["PROBING", "LOCKED", "RE_PROBING", "CAPPED", "PAUSED"]
    probe_pct: float                  # impact % being tried (PROBING/RE_PROBING only)
    sweet_spot_pct: Optional[float]   # locked impact %, None when not locked
    consecutive_failures: int         # in LOCKED mode; triggers RE_PROBING at 2
    capped_entry_block: Optional[int] # set when entering CAPPED, used for 3-block reset
    paused_entry_block: Optional[int] # set when entering PAUSED, used for 30-block reset
    cap_loop_count: int               # incremented on every CAPPED entry; reset on PAUSED exit
    lp_add_failure_count: int         # consecutive LP-add failures; cleared on success or after limit
    pending_sell: Optional[PendingSell]
    last_arb_gibs: Optional[int]      # most recent arb bot buy size (wei) → feeds lp_add_target
    last_transition_ts: str           # ISO timestamp of last state transition (for status())

@dataclass
class PendingSell:
    sell_gibs_wei: int
    sell_block: int                   # from TX receipt, not w3.block_number
    sell_tx_hash: str
    impact_pct_at_sell: float
    deadline_block: int               # sell_block + PROBE_RESPONSE_WINDOW_BLOCKS

# Window semantics: arb events are accepted at blocks (sell_block, deadline_block]
# i.e. EXCLUSIVE of sell_block (no self-match) and INCLUSIVE of deadline_block.
# At default window=5: a sell at block 100 accepts arbs at blocks 101..105.
# At block 106, the window has passed; check_arb_response resolves to NO_RESPONSE.
```

### Transition table

| From | Event | To | Side effect |
|---|---|---|---|
| PROBING | arb_detected | LOCKED | sweet_spot ← probe_pct; failures ← 0; last_arb_gibs ← size |
| PROBING | no_response | PROBING | probe_pct += 1.0; if > MAX → CAPPED, cap_loop_count += 1, capped_entry_block ← now |
| LOCKED | arb_detected | LOCKED | failures ← 0; last_arb_gibs ← size |
| LOCKED | no_response | LOCKED | failures += 1; if failures ≥ 2 → RE_PROBING |
| RE_PROBING entry | (auto) | RE_PROBING | probe_pct ← max(BASELINE, sweet_spot − 1.0); sweet_spot ← None |
| RE_PROBING | arb_detected | LOCKED | sweet_spot ← probe_pct; failures ← 0; last_arb_gibs ← size |
| RE_PROBING | no_response | RE_PROBING | probe_pct += 1.0; if > MAX → CAPPED, cap_loop_count += 1, capped_entry_block ← now |
| CAPPED | next_sell_gibs called | CAPPED | return BASELINE_PCT-sized sell (fallback floor behavior) |
| CAPPED | current_block ≥ capped_entry_block + 3 | PROBING | probe_pct ← BASELINE_PCT |
| any | cap_loop_count ≥ 10 | PAUSED | paused_entry_block ← now |
| PAUSED | next_sell_gibs called | PAUSED | return BASELINE_PCT-sized sell |
| PAUSED | current_block ≥ paused_entry_block + 30 | PROBING | cap_loop_count ← 0; probe_pct ← BASELINE_PCT |

### Invariants

1. `sell_gibs_wei = solve_for_impact(probe_pct or sweet_spot_pct, current_reserves)` — the impact-to-size conversion uses **current** reserves at the moment of `next_sell_gibs`, not cached values
2. `last_arb_gibs` is set ONLY when an arb is actually detected; cleared when LP-add succeeds
3. Only ONE pending sell at a time — `record_sell` called while a previous sell is still within its window is a usage error and raises
4. If `next_sell_gibs` is called while `pending_sell` is not None and within deadline, it returns 0 (skip cycle)
5. CAPPED and PAUSED both fall back to baseline behavior — they degrade but never halt E2
6. State file writes are atomic and group-readable (mode 664)

### Sizing math

For target impact `p` (decimal fraction, e.g. 0.03 for 3%) on a pool with current reserves `(R_gibs, R_wpls)`, the GIBS amount to sell is:

```
x_gibs = R_gibs × (sqrt(1 + p) − 1) / 0.997
```

Where `R_gibs` is the GIBS-side reserve at the moment of the call (input side, since we are selling GIBS into the pool). The 0.997 factor accounts for the V2 0.3% LP fee. Derived from the Uniswap v2 small-impact approximation. Accurate to within ~5% for impacts in the 0.3% to 10% range we use. A more precise Newton-iteration version is available if needed but adds complexity for marginal benefit.

Edge case: if `hub_gibs_balance == 0`, `next_sell_gibs` returns 0 regardless of state. The state machine still ticks toward CAPPED/PAUSED auto-resets based on block number, so a temporary depletion of Hub GIBS does not stall the controller.

### Configurable constants

All in `core/config.py`:

```python
PROBE_BASELINE_PCT = 0.3              # starting impact, matches current ~8 GIBS floor sell
PROBE_STEP_PCT = 1.0                  # linear escalation per failed probe
PROBE_MAX_IMPACT_PCT = 10.0           # safety cap before CAPPED state
PROBE_RESPONSE_WINDOW_BLOCKS = 5      # blocks to wait for arb response
PROBE_FAILURE_THRESHOLD = 2           # consecutive failures in LOCKED → RE_PROBING
PROBE_CAPPED_AUTO_RESET_BLOCKS = 3    # CAPPED → PROBING after this many blocks
PROBE_CAP_LOOP_WARN_THRESHOLD = 5     # log WARN after this many cap_loop entries
PROBE_CAP_LOOP_PAUSE_THRESHOLD = 10   # PAUSED after this many cap_loop entries
PROBE_CAP_LOOP_PAUSE_BLOCKS = 30      # PAUSED → PROBING after this many blocks
PROBE_LP_ADD_RETRY_LIMIT = 3          # max consecutive LP-add failures before clearing target
```

---

## Per-cycle data flow

### Happy path (probe succeeds, LP-add follows in next cycle)

```
E2 cycle starts
├─ 1. E2 reads current pool reserves (existing simulate code)
├─ 2. E2 calls probe.check_arb_response()
│       PENDING        → return early, EngineResult(skip=True)
│       ARB_DETECTED   → state advances; last_arb_gibs set; continue
│       NO_RESPONSE    → state advances; failures or probe_pct steps; continue
│
├─ 3. E2 calls probe.lp_add_target()
│       returns gibs_wei → call hub.mintLPAndSell(
│           mint_count=ceil(gibs_wei / 1e18),
│           lp_bps=10000, burn_bps=0,
│           lp_dex=1, min_sell_out=0,
│           sell_path=[], sell_dex=0,
│           value=wpls_for_lp_side  # from Joey via msg.value
│         )
│       → on success: probe.last_arb_gibs ← None
│       → on failure: lp_add_failure_count += 1; retry next cycle
│
├─ 4. E2 calls probe.next_sell_gibs(hub_gibs_bal, reserves)
│       returns 0    → skip sell this cycle (PENDING or 0 from invariant 4)
│       returns N    → E2 ensures Hub has at least N GIBS (primeGibs if not),
│                       then submits the sell via existing pipeline
│
├─ 5. E2 submits the sell TX (mintLPAndSell with lp_bps=0, sell_bps=10000)
│
├─ 6. On TX mine: E2 calls probe.record_sell(receipt.size, receipt.blockNumber, tx_hash)
│       → controller stores PendingSell, deadline = block + 5
│
└─ 7. E2 sleeps, next cycle begins at step 1
```

### Off-path A: PENDING

`check_arb_response()` returns PENDING → steps 3-6 skip → E2 returns `EngineResult(success=False, notes="probe pending")` → strategist evaluates other engines (existing behavior, no special fallback code).

### Off-path B: probe escalation (no_response in PROBING/RE_PROBING)

Step 2 returns NO_RESPONSE → controller advances `probe_pct += 1.0` → step 3 returns None (no LP add owed) → step 4 returns a LARGER GIBS amount than last cycle → step 5 submits the bigger sell → window reset.

### Off-path C: CAPPED fallback

Step 4 returns `BASELINE_PCT`-sized GIBS amount because controller is in CAPPED → E2 executes a normal floor sell → `record_sell` still called (the controller wants to know if even the baseline triggers an arb during the cooldown). After 3 blocks, next call to `next_sell_gibs` triggers the auto-reset to PROBING.

### Off-path D: PAUSED fallback

Same as CAPPED but with a 30-block timer instead of 3.

### LP-add mechanics

When `lp_add_target()` returns `gibs_wei`:

1. Compute `mint_count = ceil(gibs_wei / 1e18)`
2. Compute `wpls_needed` for the LP side from current pool reserves: `wpls_needed = (gibs_wei × R_wpls / R_gibs) × 1.05` (5% slippage cushion)
3. Verify Joey wallet has `wpls_needed + gas` PLS available; if not, fail-fast with a logged error
4. Submit `hub.mintLPAndSell(mint_count, 10000, 0, 1, 0, [], 0)` with `value=wpls_needed`
5. On success: set `last_arb_gibs = None`, log `lp_add` event
6. On failure: increment `lp_add_failure_count`; after 3 consecutive failures, clear `last_arb_gibs` and log `WARN probe: abandoning LP-add after 3 failures — manual check recommended`

The Hub's existing `mintLPAndSell` already supports `lp_bps=10000` as an LP-only variant. No new contract function needed.

---

## Persistence

### File format

`scripts/Joystick/data/probe_state.json`:

```json
{
  "schema_version": 1,
  "updated_at": "2026-04-08T17:30:00Z",
  "updated_block": 26232900,
  "state": {
    "mode": "LOCKED",
    "probe_pct": 4.0,
    "sweet_spot_pct": 4.0,
    "consecutive_failures": 0,
    "capped_entry_block": null,
    "paused_entry_block": null,
    "cap_loop_count": 0,
    "last_arb_gibs_wei": "47880000000000000000",
    "lp_add_failure_count": 0
  },
  "stats": {
    "sells_total": 142,
    "arbs_detected_total": 12,
    "cap_entries_total": 0,
    "pause_entries_total": 0,
    "sweet_spot_history": [
      {"ts": "2026-04-08T17:00:00Z", "block": 26232800, "sweet_spot_pct": 3.0},
      {"ts": "2026-04-08T17:15:00Z", "block": 26232870, "sweet_spot_pct": 4.0}
    ]
  }
}
```

### What survives restart

`mode`, `probe_pct`, `sweet_spot_pct`, `consecutive_failures`, `capped_entry_block`, `paused_entry_block`, `cap_loop_count`, `last_arb_gibs`, `lp_add_failure_count`, all `stats` fields.

### What does NOT survive restart

`pending_sell` — discard on restart and start fresh. A stale block reference against a moving chain head is worse than missing one probe cycle.

### Write cadence

Atomic write on every state transition. Not on every cycle. Average ~0.01 writes/second.

### Atomic write pattern

Same pattern fixed in `lp_fees.py` earlier:

```python
fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
with os.fdopen(fd, "w") as f:
    json.dump(payload, f, indent=2, default=str)
os.chmod(tmp, 0o664)
os.replace(tmp, path)
```

The 0o664 chmod ensures the file is readable by the joystick group (dashboard user) without re-hitting the cross-user permission bug from earlier this session.

### Load on startup

Load `probe_state.json` if present and valid. If missing or unparseable, log warning, rename bad file to `probe_state.json.broken-<timestamp>`, initialize fresh state at `mode=PROBING, probe_pct=BASELINE_PCT`. Newer schema versions are also treated as "corrupt" (a newer bot wrote it; older bot doesn't know how to read it; safer to start fresh).

---

## Observability

### 1. Python logger (INFO level → bot stdout)

One line per state transition, one line per sell decision:

```
probe INFO  state: PROBING (probe=0.3%) → PROBING (probe=1.3%)  reason: no_response
probe INFO  state: PROBING (probe=3.3%) → LOCKED (sweet_spot=3.3%)  arb=47.88 GIBS tx=0x...
probe INFO  sell: 8.25 GIBS (impact=0.29%, baseline)  [LOCKED, sweet_spot=3.3%]
probe INFO  lp_add: 47.88 GIBS + 2065 PLS → LP (matching last arb)
probe WARN  state: RE_PROBING (probe=2.3%) → CAPPED  cap_loop_count: 3
```

### 2. Structured JSON-L event log

`scripts/Joystick/data/events/probe.json` — one line per event, schema:

```json
{"ts": "2026-04-08T17:30:05Z", "event": "sell", "block": 26232900,
 "sell_gibs_wei": "8250000000000000000", "impact_pct": 0.29,
 "mode": "LOCKED", "sweet_spot_pct": 3.3, "tx": "0x..."}

{"ts": "2026-04-08T17:30:55Z", "event": "arb_detected", "block": 26232905,
 "arb_gibs_wei": "47880000000000000000", "response_blocks": 5,
 "by_addr": "0xc078c8da..."}

{"ts": "2026-04-08T17:30:56Z", "event": "state_transition",
 "from": "LOCKED", "to": "LOCKED", "reason": "arb_detected",
 "consecutive_failures": 0}

{"ts": "2026-04-08T17:31:10Z", "event": "lp_add", "block": 26232910,
 "gibs_wei": "47880000000000000000", "wpls_wei": "2065...",
 "tx": "0x..."}
```

Uses the existing `core.event_logger.events.log()` helper. Same channel as engine event logs.

### 3. status() snapshot

Returns a dict consumable by `bot.py --status`, future dashboard routes, or operators inspecting state interactively:

```python
{
  "mode": "LOCKED",
  "sweet_spot_pct": 3.3,
  "probe_pct": None,
  "consecutive_failures": 0,
  "pending_sell": None,
  "last_arb_gibs": 47.88,         # human-readable GIBS, not wei
  "cap_loop_count": 0,
  "lp_add_failure_count": 0,
  "last_transition_ts": "2026-04-08T17:30:56Z",
  "stats": {
    "sells_total": 142,
    "arbs_detected_total": 12,
    "avg_arb_gibs": 44.3,
    "cap_entries_total": 0,
    "pause_entries_total": 0
  }
}
```

### Stats accounting rules

- `sells_total` increments on every successful `record_sell` call
- `arbs_detected_total` increments on every transition into ARB_DETECTED resolution
- `avg_arb_gibs` is computed on read as `sum(arb_sizes) / arbs_detected_total` (running average maintained internally)
- `cap_entries_total` increments on every transition into CAPPED
- `pause_entries_total` increments on every transition into PAUSED
- `sweet_spot_history` ring buffer (max 50 entries) appends on every transition INTO LOCKED with the new sweet_spot_pct, ts, and block

---

## Error handling

### 1. RPC / event query failures

`eth.get_logs` exception → retry once on fallback RPC (`core.chain._read_pool` already handles failover) → on second failure, log WARN and return PENDING (treat window as still-open). Self-corrects on next cycle. At most 5 blocks of delayed transition per outage.

### 2. Sell TX failure (revert at simulate, estimate, submit, or receipt)

E2 calls `record_sell` ONLY after a successful mine. If the sell fails at any layer, controller state is untouched — as if the cycle never happened. Same size will be tried next cycle. Correct behavior: sell-failure means infrastructure problem, not sizing problem.

Soft sanity guard in `next_sell_gibs`: if `target_size > hub_gibs_balance` AND priming would be required, cap the return at `hub_gibs_balance` and log WARN. Prevents impossible sells.

### 3. LP-add TX failure

Increment `lp_add_failure_count`. `last_arb_gibs` stays set so next cycle retries. After 3 consecutive failures, force-clear `last_arb_gibs` and log WARN. Prevents poisoned state from blocking all future probes.

### 4. Hostile market (chronic CAP loops)

`cap_loop_count ≥ 5` → log WARN. `cap_loop_count ≥ 10` → enter PAUSED for 30 blocks (~5 min), counter resets on exit. Both PAUSED and CAPPED fall back to baseline floor behavior, so E2 keeps earning at normal rates. The throttle bounds slippage exposure during extended hostile windows.

### 5. State file corruption or schema drift

- Unparseable JSON → rename to `.broken-<ts>`, reinit fresh
- Unknown fields → ignore, use known fields
- Newer schema version → treat as corrupt, reinit
- Older schema → forward-compat shim if added later (not needed for v1)

### 6. Block number race in record_sell

Always use `receipt.blockNumber` (not `w3.eth.block_number` at submit time) to anchor `deadline_block`. Eliminates the drift window between TX submission and receipt.

### Scope exclusions

- Hub auth changes (operational concern, not controller scope)
- Chain reorgs (assumed rare and transient on PulseChain; `eth_getLogs` returns canonical chain)
- Adversarial bots gaming the controller (out of scope; would show in logs if it happens)

### Resilience posture

Fail-safe, not fail-secure. Every error path has a bounded retry count and a visible log message. The hardest failure mode (chronic hostility) has both soft (warning) and hard (5-min pause) throttles. CAPPED and PAUSED both fall back to productive baseline floor behavior, so E2 never goes fully idle due to a probe failure.

---

## Testing

### Layer 1: state machine unit tests

`scripts/Joystick/tests/test_probe_controller.py`. No network. Mock the clock, mock `get_logs`, never touch a real RPC.

Required test cases (each is a pytest function):

- `test_init_fresh`
- `test_init_restore`
- `test_init_corrupt_file`
- `test_probe_to_lock_on_arb`
- `test_probe_escalates_on_no_response`
- `test_probe_hits_cap`
- `test_capped_auto_resets_after_3_blocks`
- `test_capped_falls_back_to_baseline_size`
- `test_locked_resets_failure_counter_on_arb`
- `test_locked_increments_failures_on_no_response`
- `test_locked_to_reprobing_after_2_failures`
- `test_reprobing_starts_at_sweet_spot_minus_1`
- `test_reprobing_to_lock_on_arb`
- `test_reprobing_hits_cap`
- `test_cap_loop_count_triggers_pause_at_10`
- `test_paused_auto_resets_after_30_blocks`
- `test_pending_sell_blocks_new_sell`
- `test_response_window_respects_deadline`
- `test_lp_add_target_matches_arb_size`
- `test_lp_add_target_cleared_after_use`
- `test_sell_size_capped_at_hub_balance`
- `test_sizing_math_matches_uniswap_v2`

Target: 100% branch coverage on the state machine. Total runtime <2s.

### Layer 2: Anvil fork integration tests

`scripts/Joystick/tests/test_probe_integration.py`. Uses existing `tests/conftest.py` Anvil fixtures and `tests/anvil_helpers.py` block manipulation.

Required test cases:

- `test_real_sell_triggers_record_sell`
- `test_arb_event_detected_via_get_logs`
- `test_no_response_resolves_after_5_blocks`
- `test_lp_add_after_arb_via_real_hub`
- `test_capped_fallback_keeps_earning`

Validates that the controller correctly bridges to real Hub calldata, real Swap event parsing, and real reserves math.

### Layer 3: mainnet smoke test (manual, supervised)

Progressive rollout pattern (same approach used during ladder rescue debug earlier this session):

1. Set `PROBE_MAX_IMPACT_PCT = 2.0` (low cap, ~40 PLS slippage exposure worst case)
2. Run with `--once` first; observe log output
3. Inspect `data/events/probe.json` for expected events
4. Run continuously for 10 minutes; verify state transitions, LP-add execution, arb detection
5. If 2% succeeds, raise to 5%; another 10-minute run
6. If 5% succeeds, raise to designed 10% default

### Test infrastructure

All required test infrastructure already exists:

- `tests/conftest.py` Anvil fixtures (session-scoped)
- `tests/anvil_helpers.py` fork management + block manipulation
- `tests/test_joystick_hub.py` working Hub call harness to model from
- `core.event_logger` for verifying probe.json contents

No new test infrastructure required.

### Out of scope for testing

- Long-running stability (relies on production logs + manual review over hours/days)
- Chain reorg behavior (rare on PulseChain, expensive to simulate, assumed handled by `eth_getLogs`)
- Interaction with E2 LADDER rescue path (kept separate, documented as out of scope)
- Dashboard route behavior (no dashboard route in this spec)

---

## Open questions

None. All design decisions are locked via the brainstorming session. The user has approved each section.

---

## Known follow-ups (not in this design)

These are deliberate omissions for scope control. Each is a candidate for a separate spec/plan after this one ships:

- **Multi-pair probe controllers** (one per GIBS pair) — once GIBS/WPLS works, instantiate more
- **Dashboard route** for `/api/probe/status` and `/api/probe/events`
- **Chart-friendly history endpoint** showing sweet_spot_pct over time
- **Adaptive max-impact cap** based on Joey wallet PLS balance (auto-tightens when PLS is low)
- **Coordination with E2 LADDER rescue** — currently the two paths are independent; eventually they could share state
- **Probe controller for non-Joey LP positions** — if other Dysnomia players want to run this against their own pools

---

## Constants reference

For convenience, all configurable constants in one place. All live in `core/config.py`:

| Constant | Default | Meaning |
|---|---|---|
| `PROBE_BASELINE_PCT` | 0.3 | Starting impact %, matches current ~8 GIBS floor sell |
| `PROBE_STEP_PCT` | 1.0 | Linear escalation step per failed probe |
| `PROBE_MAX_IMPACT_PCT` | 10.0 | Safety cap before CAPPED state |
| `PROBE_RESPONSE_WINDOW_BLOCKS` | 5 | Blocks to wait for arb response |
| `PROBE_FAILURE_THRESHOLD` | 2 | Consecutive LOCKED failures → RE_PROBING |
| `PROBE_CAPPED_AUTO_RESET_BLOCKS` | 3 | CAPPED → PROBING after this many blocks |
| `PROBE_CAP_LOOP_WARN_THRESHOLD` | 5 | Log WARN after this many cap_loop entries |
| `PROBE_CAP_LOOP_PAUSE_THRESHOLD` | 10 | Enter PAUSED after this many cap_loop entries |
| `PROBE_CAP_LOOP_PAUSE_BLOCKS` | 30 | PAUSED → PROBING after this many blocks |
| `PROBE_LP_ADD_RETRY_LIMIT` | 3 | Max consecutive LP-add failures before clearing target |

---

## Files that will be touched

**New**:
- `scripts/Joystick/core/probe_controller.py` (~400-500 lines)
- `scripts/Joystick/tests/test_probe_controller.py` (unit tests)
- `scripts/Joystick/tests/test_probe_integration.py` (Anvil tests)
- `scripts/Joystick/data/probe_state.json` (runtime state, gitignored)
- `scripts/Joystick/data/events/probe.json` (event log, gitignored)

**Modified**:
- `scripts/Joystick/core/config.py` (add 10 PROBE_* constants)
- `scripts/Joystick/engines/dss.py` (wire controller into `_execute_harvest`, ~50 line diff)
- `scripts/Joystick/bot.py` (instantiate singleton, pass to DSSEngine)

**Untouched**:
- `engines/arb.py` (E1 RAZOR — different concern entirely)
- `oracle/ladder_oracle.py` (rescue path, separate from probe)
- `_execute_ladder` in `dss.py` (rescue path, kept independent)
- All dashboard files (no route in this design)
- All LP fee accounting modules (orthogonal to probing)
