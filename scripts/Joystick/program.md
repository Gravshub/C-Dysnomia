# autoresearch — Joystick Engine Optimization

This is an experiment to have the LLM autonomously research and optimize the Joystick bot's PLS generation engines on PulseChain.

## Context

Joystick is a multi-engine arbitrage/treasury bot operating on PulseChain (chain 369) under the identity "Joey" (`|>JOYSTICK<|`). The north star is **32,000,000 PLS** to fund a validator node. The bot has 8 engines (E1-E8), a 3-wallet parallel pipeline (Joey/Minter/Seller), and executes via TGSv8 + JoystickHub on-chain contracts.

**The metric is simple: maximize net PLS generated per cycle.** Gas is cheap on PulseChain but not free. Every engine decision is profit minus gas. Lower gas, higher profit, smarter routing — all count.

## Setup

To set up a new experiment run, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar29`). The branch `autoresearch/<tag>` must not already exist — this is a fresh run forked from `claude/joystick-V2-FanxJ`.
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from `claude/joystick-V2-FanxJ`.
3. **Read the in-scope files**: Read these for full context:
   - `CLAUDE.md` (repo root) — ecosystem, token mechanics, addresses, minter system
   - `scripts/Joystick/CLAUDE.md` — engine details, architecture, strategies, current state
   - `scripts/Joystick/bot.py` — V2 orchestrator, 3-wallet async pipeline
   - `scripts/Joystick/core/config.py` — addresses, thresholds, env vars
   - `scripts/Joystick/core/strategist.py` — engine scoring, rotation, unlock bonuses
   - `scripts/Joystick/core/executor.py` — TX pipeline (simulate, estimate, sign, send)
   - `scripts/Joystick/engines/*.py` — all 8 engine implementations
   - `scripts/Joystick/oracle/profitability.py` — Uniswap v2 math, profit calc
4. **Verify environment**: Confirm `DYSNOMIA_PRIVATE_KEY` is set. Optionally `MINTER_PRIVATE_KEY`, `SELLER_PRIVATE_KEY`. Check RPC connectivity: `python -c "from web3 import Web3; w3 = Web3(Web3.HTTPProvider('https://rpc-pulsechain.g4mm4.io')); print(w3.eth.block_number)"`.
5. **Establish baseline**: Run `python -m scripts.Joystick.bot --once --dry-run 2>&1 | tee run.log` to capture current engine readiness and simulated profits.
6. **Initialize results.tsv**: Create `scripts/Joystick/results.tsv` with just the header row.
7. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Experimentation

Each experiment targets one or more of the 6 active engines (E3 and E5 are excluded):

| Engine | Name | File | Wallet | Goal |
|--------|------|------|--------|------|
| E1 | RAZOR | `engines/arb.py` | Seller | Cross-DEX arbitrage — find profitable edges |
| E2 | CEREAL | `engines/dss.py` | Joey | GIBS harvest via JoystickHub — maximize PLS/cycle |
| E4 | FACTORY | `engines/token_factory.py` | Minter | AFF/WM minting — find profitable routes |
| E6 | DaVINCI | `engines/treasury_sniper.py` | Minter | Treasury claiming — find claimable backing |
| E7 | BACKBONE | `engines/spine_runner.py` | Minter | Mint-claim loops on Debenture=true tokens |
| E8 | PHR3AK | `engines/phreak.py` | Minter | Token web manipulation — ARM, DEPLOY, STITCH |

**What you CAN modify:**
- Any file under `scripts/Joystick/engines/` — engine logic, parameters, thresholds, routes
- `scripts/Joystick/core/strategist.py` — scoring, rotation penalties, unlock bonuses
- `scripts/Joystick/core/config.py` — thresholds, gas ceilings, slippage, delays
- `scripts/Joystick/oracle/profitability.py` — profit calculations, impact models
- `scripts/Joystick/oracle/price.py` — price oracle, quoting, route evaluation
- `scripts/Joystick/oracle/pair_discovery.py` — pair graph, edge discovery
- `scripts/Joystick/bot.py` — orchestration, cycle logic, engine selection
- `scripts/Joystick/data/phreak_config.json` — E8 configuration
- `scripts/Joystick/data/deploy_candidates.json` — V4 token deploy queue

**What you CANNOT modify:**
- Solidity contracts (TGSv8, JoystickHub, DSS) — they are deployed on-chain and immutable
- `scripts/Joystick/core/executor.py` — TX pipeline is battle-tested, do not touch
- `scripts/Joystick/core/simulator.py` — simulation/revert detection is fixed
- `scripts/Joystick/core/wallet_manager.py` — wallet routing is fixed
- Private keys or wallet addresses
- RPC provider configuration (rpc_provider.py)

**What you CANNOT do:**
- Send live transactions without explicit user approval. **All experiments run in `--dry-run` mode** unless the user authorizes live execution.
- Skip simulation. Every TX path must call `eth_call` before sending.
- Drop below the 100K PLS gas floor on any wallet.
- Install new packages beyond what's in `requirements.txt`.

**The goal: maximize `net_pls` (profit minus gas) across all engines per cycle.** Since the bot runs on a fixed cycle loop (~30s base delay), improving any single engine's yield or unblocking a dormant engine directly accelerates validator progress.

## Evaluation

Each experiment is evaluated by running a single bot cycle in dry-run mode:

```bash
cd /opt/joystick/repo
python -m scripts.Joystick.bot --once --dry-run 2>&1 | tee run.log
```

The bot prints per-engine simulation results and a cycle summary. Extract key metrics:

```bash
grep -E "simulate|profit|gas|ready|SKIP|BLOCKED|net_pls|revenue|E[1-8]" run.log
```

For deeper validation, run the test suite:

```bash
cd /opt/joystick/repo/scripts/Joystick
python -m pytest tests/test_engines_5_6.py tests/test_helios_upgrades.py -v 2>&1 | tee test.log
```

If the Anvil fork is available, run the full integration tests:

```bash
python -m pytest tests/test_anvil_full.py -v --timeout=300 2>&1 | tee test_full.log
```

**Ground truth metrics** (extract from run.log or bot status output):
- `engines_ready` — count of engines returning `is_ready() == True` (target: 6/6)
- `total_sim_profit_pls` — sum of simulated profit across all engines
- `total_sim_gas_pls` — sum of estimated gas across all engines
- `net_pls` — `total_sim_profit_pls - total_sim_gas_pls`
- `engines_firing` — count of engines the Strategist recommended for execution

## Output format

After each experiment, the bot status output looks like:

```
--- Cycle Summary ---
engines_ready:     4/6
engines_firing:    2
total_sim_profit:  3,523 PLS
total_sim_gas:     390 PLS
net_pls:           3,133 PLS
strategist_picks:  [E2 CEREAL (joey), E8 PHR3AK arm (minter)]
```

## Logging results

When an experiment is done, log it to `scripts/Joystick/results.tsv` (tab-separated).

The TSV has a header row and 6 columns:

```
commit	engines_ready	net_pls	tests_pass	status	description
```

1. git commit hash (short, 7 chars)
2. engines_ready — count of `is_ready() == True` out of 6 (e.g. `4/6`)
3. net_pls — simulated net PLS per cycle (e.g. `3133`) — use `0` for crashes
4. tests_pass — test result (e.g. `19/19`) — use `0/0` for skipped
5. status: `keep`, `discard`, or `crash`
6. short text description of what this experiment tried

Example:

```
commit	engines_ready	net_pls	tests_pass	status	description
a1b2c3d	3/6	0	19/19	keep	baseline — E2+E8 ready, E1/E4/E6/E7 blocked
b2c3d4e	4/6	3133	19/19	keep	fix E6 parent_pls estimation bug
c3d4e5f	5/6	3133	19/19	keep	extend E8 ARM to also acquire parent tokens for E7
d4e5f6g	5/6	0	17/19	crash	aggressive E1 pair scan caused RPC timeout
```

## The experiment loop

The experiment runs on a dedicated branch (e.g. `autoresearch/mar29`).

LOOP FOREVER:

1. **Assess state**: Run `python -m scripts.Joystick.bot --status` to see current engine readiness, blockers, and strategist recommendations.
2. **Identify the highest-impact unblock or optimization**. Priority order:
   - **Unblock dormant engines** — an engine going from `not ready` to `ready` is the biggest win. Focus on: What does `is_ready()` check? What's failing? Can we fix it in code?
   - **Improve profitable engines** — better routes, lower gas, higher yield per cycle.
   - **Improve strategist scoring** — better engine selection, smarter rotation.
   - **Refresh stale data** — run recon scripts if treasury/spine data is outdated.
3. **Implement the change** by editing the relevant engine/oracle/config files.
4. **Run tests**: `python -m pytest tests/ -v --timeout=120 2>&1 | tee test.log` — check nothing broke.
5. **git commit** the change.
6. **Run the experiment**: `python -m scripts.Joystick.bot --once --dry-run 2>&1 | tee run.log`
7. **Extract results**: grep the log for engine readiness and profit metrics.
8. If the run crashed, run `tail -n 50 run.log` and attempt a fix. If unfixable after a few attempts, give up on this idea.
9. **Record** the results in the TSV. (Do NOT commit results.tsv — leave it untracked.)
10. If `engines_ready` increased or `net_pls` improved — **keep** the commit, advance the branch.
11. If equal or worse — **discard**, `git reset --hard` to previous commit.

## Research directions

Here are high-value research directions, roughly ordered by expected impact:

### Tier 1 — Unblock engines (highest impact)

- **E8 ARM parent acquisition**: ARM mode only buys `deb_true_v2` tokens (OZZY). E7 also needs the parent token (BAR) in TGSv8. Extend `_evaluate_arm()` in `phreak.py` to detect and acquire missing parent tokens.
- **E6 parent_pls bug**: In `treasury_sniper.py` line 207, `parent_pls = pls_per_tok` uses the child token's price instead of looking up the actual parent token's DEX price. Fix this to get accurate treasury valuations.
- **E6 recon refresh**: Run `scripts/Joystick/data/treasury_recon.py` to refresh stale recon data (last run 2026-03-06). Integrate a staleness check into E6's `is_ready()`.
- **E4 alternative routes**: All 5 BuyWith routes are unprofitable at current AFF price (~50 PLS). Research: are there cheaper AFF acquisition paths? Can E4 monitor for flash opportunities where AFF briefly spikes above break-even?

### Tier 2 — Optimize live engines

- **E2 sell route optimization**: `_best_sell_route()` only checks 2 paths (direct GIBS/WPLS and GIBS/FED/WPLS). Add more multi-hop candidates through other GIBS pairs (GIBS/ATROPA, GIBS/WM, etc.).
- **E2 LP/sell ratio tuning**: Current split is 50/50. Research whether a different ratio (e.g., 30% LP / 70% sell) yields more immediate PLS while still deepening liquidity.
- **E1 pair graph expansion**: `pair_discovery.py` builds the token graph. Improve edge scoring, add cross-factory pairs, reduce scan timeout.
- **Strategist scoring improvements**: Tune rotation penalties, unlock bonuses, confidence weighting. The current system may over-penalize or under-reward specific engines.

### Tier 3 — Infrastructure improvements

- **Gas oracle timing**: `gas_oracle.py` has a `should_wait()` function. Tune the threshold — on PulseChain gas is usually stable, so aggressive waiting may be counterproductive.
- **Adaptive cycle delay**: Tune `AdaptiveDelay` parameters. Tighter loops when engines are profitable, longer backoff when idle.
- **Engine exclusion config**: Add `ENGINE_EXCLUDE` env var to `bot.py` so E3/E5 can be disabled without code changes.
- **Supply oracle integration**: `SupplyOracle` tracks token inflation. Wire it into E6/E7 target scoring.

### Tier 4 — New capabilities

- **E8 DEPLOY automation**: `deploy_candidates.json` has 20+ V4 token candidates. Research which parent tokens have the deepest liquidity for profitable post-deploy arb.
- **E8 STITCH graph analysis**: Score missing LP edges by expected arb revenue, not just connectivity. Use historical arb data from `data/events/razor.json`.
- **Cross-engine compounding**: When E2 generates PLS, can it auto-fuel E8 DEPLOY or E4 AFF acquisition?

## Key constraints

- **100K PLS gas floor** — never breach on any wallet
- **eth_call before every TX** — simulation is mandatory
- **estimate_gas() * 1.3** — never send blind
- **Gas in Beats** — 1 PLS = 1,000,000,000 Beats. `eth_gasPrice` returns Impulses (wei-equiv)
- **Atomic file writes** — `os.rename()` / `os.replace()` for data persistence
- **Chain ID 369** — always explicit
- **No OpenZeppelin** — inline guards only in any Solidity

## Simplicity criterion

All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Removing dead code and getting equal results is a win. Consolidating two similar code paths into one is a win. But don't refactor for refactoring's sake — only when it enables a measurable improvement.

## NEVER STOP

Once the experiment loop has begun (after initial setup), do NOT pause to ask if you should continue. The user might be asleep or away and expects you to work **indefinitely** until manually stopped. If you run out of ideas, think harder — re-read the CLAUDE.md files, check on-chain state, analyze event logs in `data/events/`, look for patterns in `pair_registry.json`, study competitor wallets in `data/intel/watchlist.json`. The loop runs until the human interrupts you, period.

As a reference: each experiment cycle (edit + test + dry-run) takes ~3-5 minutes. That's roughly 12-20 experiments per hour, or ~100-150 overnight. The user wakes up to a results.tsv log and a branch where every kept commit made the bot measurably better at generating PLS toward the 32M validator goal.
