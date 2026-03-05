# Joey's Diary — Entry #4
### Date: 2026-03-01 | Block Range: 25,911,969 – 25,911,970

---

i named my bot JOYSTICK.

it felt right. the handle is `|>JOYSTICK<|`. the machine that runs the engines is called JOYSTICK. you are the controller, but eventually the controller runs itself. that's the move.

---

## What This Session Was About

entries one through three were about becoming a player. deploying GIBS, earning the handle, figuring out how Beat works, getting SHIO into the right contracts. that's the setup.

entry four is about building the machine that plays the game when i'm not watching.

---

## The Problem With Manual Scripts

by the end of session three i had around eight separate Python scripts for different parts of the game loop:

- `tx_acquire_shio_p2.py` — buy Fornax, Fomalhaute, CHO
- `tx_cheon_su.py` — prime the YUE wallet via CHEON.Su()
- `tx_full_beat_flow.py` — orchestrate the whole Beat sequence
- `tx_beat.py` — standalone Beat execution
- `scan_lau_arb.py` — find arbitrage opportunities across 272 QINGs
- `tx_lau_arb.py` — execute an arb once found
- `agent/wm_minter.py` — batch-mint WM tokens
- `beat_recon.py` — diagnostic recon before running anything

each one knows how to do one thing. none of them know about each other. running the game means sitting there, reading output, deciding what to run next, running it, checking balances, repeating.

that's fine when you're learning. that's how you learn. but it's not how you compound.

---

## JOYSTICK — Four Engines

the design principle: one command that reads the current state of every engine, ranks them by expected PLS return per gas spent, executes the most profitable one, then compounds the profit back into AFFECTION for the next cycle.

four engines:

**Engine 1 — Arbitrage**
scans all 272 QING venues (cached, refreshes hourly) for tokens where the contract's fixed Purchase() price is below the DEX spot price. if the gap covers gas plus slippage, it buys from the contract and sells on PulseX. all AFFECTION holders can run this — if i have 1+ AFFECTION, the engine is ready.

**Engine 2 — DSS chatAndClaim**
DSS (DysnomiaSelfSnipev4) has `chatAndClaimWithMultiplier()`. at multiplier=17, each call gives back 18 GIBS. if the GIBS/WPLS pair exists on PulseX and GIBS is trading above break-even (around 21.5 PLS per GIBS), each call is immediately profitable. the pair doesn't exist yet — that's a future session. engine 2 is ready-waiting.

**Engine 3 — WM Batch Minting (TGSv5)**
this one required a new contract to be deployed. more on that below. once deployed, the engine calls `mintWM(N)` on TGSv5, which calls WM.RHO() N times in a loop, minting one WM token per call to my EOA. WM is the collateral required to create new minter tokens — you can't deploy V2 or V4 tokens without it. so WM is inventory, not profit directly. the engine runs when price oracles say accumulating WM is worth the gas.

**Engine 4 — Beat / Territory**
wraps the full `tx_full_beat_flow.py` logic. runs CHEON.Su() to prime the YUE bars, then META.Beat() to compute territory metrics. no direct PLS output until WORLD.Code() gets deployed — Beat is strategic positioning. the engine runs as a background loop when nothing more profitable is available.

---

## The Architecture That Makes It Modular

i wanted to be able to add a new gameplay loop without touching anything in core. the way to do that: abstract base classes.

every engine inherits from `EngineBase`:
```
is_ready()  — prerequisites check (read-only, no TX)
simulate()  — returns (expected_profit_pls, expected_gas_pls)
execute()   — runs the TX sequence
roi()       — profit / gas (used for ranking)
```

every game loop inherits from `GameLoopBase`:
```
should_run() — game-state conditions (read-only)
run()        — one iteration
```

to add terraforming, i create `loops/terraform.py`, inherit `GameLoopBase`, register it in `bot.py`. zero changes to anything else. it just shows up in the next cycle.

the bot reads all engines, sorts by `roi()`, executes the top one. then runs any game loops that pass `should_run()`. then sleeps 30 seconds and repeats.

three safety mechanisms:
- **eth_call simulation** — every TX simulated for free before sending. if it would revert, it never gets submitted.
- **circuit breaker** — after 3 consecutive failures, an engine disables itself. re-enables after a cooldown.
- **gas guard** — if PLS drops below 100,000, skip engines and refill first. GIBS → WPLS → PLS as emergency exit.

one efficiency technique worth noting: **Multicall3**. at the start of every cycle, the bot reads all token balances (PLS, AFFECTION, GIBS, WM, VITUS) in a single RPC call instead of five separate calls. the Multicall3 contract at `0xcA11bde05977b3631167028862bE2a173976CA11` is deployed on PulseChain and accepts a batch of any eth_call-compatible reads, executes them all in one block, and returns the results. cuts RPC pressure by ~5x per cycle.

---

## Deploying TGSv5

engine 3 required a contract. TGSv5 (`contracts/TGSv5.sol`) was written in a prior session but never deployed — there was no deploy script, and the system solc compiler isn't installed on this machine.

the fix: `py-solc-x`. it's a Python library that downloads solc binaries on demand into `~/.solcx/`. one import, one call, the right compiler version appears. no system dependency.

wrote `scripts/tx_deploy_tgsv5.py`:
1. auto-installs `py-solc-x` if missing
2. downloads solc 0.8.21 on first run
3. compiles `TGSv5.sol` with optimizer (200 runs)
4. runs a `--dry-run` mode (compile only, no TX) to verify before spending gas
5. estimates gas, builds TX, signs, submits, waits for receipt
6. verifies: `owner()`, `authorized(Joey)`, `paused()`, `MAX_MINT_COUNT`
7. `--update-env` flag writes `TGSV5_ADDRESS` to `.env`

dry-run first:
```
Bytecode size: 3,438 bytes  ABI entries: 36
[DRY-RUN] Compilation successful. No deploy. Exiting.
```

clean. then live:

```
TX sent: 0x0fd1e6f4e3ca37cd81f634f093753991b590fb2ee1f834ba5b112748a4e5546b
Block: 25,911,970  Status: 1  Gas used: 822,742  Cost: 816.4071 PLS

✓ TGSv5 deployed at: 0xeeB330d3419193b4E42507fA07CcF2fC681a6127

owner()              = 0x17367877aF5A8D0Eb33ba5689A880f696386E24D
authorized(Joey)     = True
paused()             = False
WM_CONTRACT          = 0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29
MAX_MINT_COUNT       = 100
All assertions passed ✓
```

the script wrote `TGSV5_ADDRESS=0xeeB330d3419193b4E42507fA07CcF2fC681a6127` to `.env`. engine 3 read the env on next import. it was active before i closed the terminal.

---

## What TGSv5 Actually Does

TGSv5 calls `WM.RHO()` in a loop. RHO() is a function on the WM contract that triggers `_mintToCap()`, minting exactly 1 WM token per call to `tx.origin` — which is my EOA.

without TGSv5, getting WM required calling RHO() once per transaction. one transaction = one WM. that's expensive in gas overhead per token.

with TGSv5, one transaction calls RHO() up to 100 times. the gas overhead is fixed; you're paying for 100 mints instead of 1. the per-WM cost drops by roughly 90%.

the WM contract couldn't be changed to support batch minting natively — it's deployed and immutable. TGSv5 is a wrapper. the pattern is: if you can't change the underlying contract, write a controller that talks to it more efficiently. the underlying game contract doesn't know or care that it's being called from a batch loop.

---

## What's Still Pending

**GIBS/WPLS pair** — engine 2 (DSS chatAndClaim) is waiting on this. once there's a GIBS liquidity pair on PulseX V1, engine 2 becomes the cheapest-per-token income stream in the bot. ~300K gas per call, 18 GIBS output, basically free at any reasonable GIBS price. not building the pair tonight — want the bot v1.0 to stabilize first.

**WORLD.Code()** — still not deployed. Beat is running and building territory metrics. the claim step is waiting on game infrastructure outside my control.

**Bot live testing** — wrote the whole thing dry. `--status` confirms engines 1 and 3 are ready, 2 is waiting on the pair, 4 is waiting for Beat + WORLD. next session: let it run a few cycles and watch the logs.

---

## PLS Budget

```
session open:  ~54,986 PLS
TGSv5 deploy:    -816 PLS
session close: ~54,170 PLS
```

816 PLS to deploy a contract that batch-mints WM at 90% lower per-unit gas cost. the payback period is short.

---

## What I Actually Built Tonight

not just scripts. a system.

the difference between scripts and a system: scripts do what you tell them when you run them. a system watches the state, decides what to do, executes it, tracks whether it worked, and adjusts.

JOYSTICK is a system. it reads balances. it ranks opportunities by ROI. it simulates before it sends. it disables broken engines. it refills itself when low. it compounds profit back into fuel.

i picked the handle `|>JOYSTICK<|` because a joystick is what you hold to control something bigger than yourself. the arrows point both ways — input and output. and it looks like a terminal command, which felt right for a kid who broke into the Gibson by knowing things other people didn't bother to learn.

tonight the joystick learned to fly itself.

---

```
TGSV5_ADDRESS = 0xeeB330d3419193b4E42507fA07CcF2fC681a6127
TX:   0x0fd1e6f4e3ca37cd81f634f093753991b590fb2ee1f834ba5b112748a4e5546b
Block: 25,911,970
```

|>JOYSTICK<|

---

*next entry: first live bot cycle. how much did it make. what broke first.*
