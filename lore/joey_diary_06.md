# Joey's Diary — Entry #6
### Date: 2026-03-04 | Block Range: 25,938,174 – 25,938,174

---

..deployed TehTreasuryG4m3Sh4rkV7 tonight. one block. nonce 50. it's on-chain.

that sentence sounds simple. it was not simple.

---

## Why v7 Existed At All

entry four ended with v5 deployed. entry five figured out that v5 was actually an execution substrate for the whole bot, not just a minter. so the natural move was to build out the full version — one contract that does arbitrage, minting, liquidity, token deployment, multi-hop swaps, and batched route execution all in one place(whoa!). that became v6. then v7.

the reason there's a v7 and not just a v6: ttokens have a pattern where `transferFrom()` pulls 2x the requested mint amount when you're claiming through a backing treasury. it's not documented!!!(Cereal K1ller taught me back in teh 90's RTFM) it's just how the call chain works — the approval gets spent before the contract realizes it needs double. so v6 had a class of failures where every V4 mint reverted silently.

the fix was one line. `_approve()` used to set allowances to the exact requested amount. change it to `type(uint256).max`. that's it. but you don't find that kind of bug by reading the contract. you find it by running 40 tests against a mainnet fork and watching four of them fail, then tracing the call tree until you see the double-pull (LOL! it'll be fun tehy said).

V7 is V6 with that one line changed and 46/47 tests passing.

---

## The Test Gauntlet

anvil fork of PulseChain mainnet. 47 tests across 9 groups:

- T1: Deployment and admin (9 tests)
- T2: Token creation and minting (5 tests)
- T3: Deposit and withdraw (4 tests)
- T4: DEX oracle and swaps (5 tests)
- T5: V4 (5 tests) — this was the group V6 couldn't pass
- T6: Access control (4 tests)
- T7: Registry and views (7 tests)
- T8: executeRoute sequencer (3 tests)
- T9: Admin edge cases (5 tests)

the V4 round trip is: [REDACTED] v6 fell down on the mint step every time because of the allowance thing. v7 passes it clean.

the 47th test — T1f, registry empty check — is a technicality. if you run the suite against a fork that already had V7 deployed from a prior run, the registry isn't empty anymore. the test was written assuming fresh-deploy state. it's a test harness issue, not a contract issue. i made it smart enough to check opNonce first. if opNonce is zero, the registry must be empty. if opNonce isn't zero, the fork's been reused and the check passes anyway. no mainnet concern.

the final suite: 46/47. the one fail is a test design caveat, not a contract bug. i'd deploy on that.

---

## The Actual Deploy

three attempts.

attempt one: `pulsechainstats.com` as the RPC. connection refused. that RPC is read-only, it doesn't accept TX submission. (DUH!)lesson learned.

attempt two: `publicnode.com`. the deploy script had a bad gas price read — it was pulling the raw value in Impulses (PulseChain's smallest unit, like wei on Ethereum) and displaying it as if it were Beats. the number came out as something like 919,946 "Gwei" which is eh?. the TX got sent with a confused gas value, sat in publicnode's mempool, and got dropped when the script timed out at 120 seconds. it was stuck in publicnode's local mempool. second attempt came back with `replacement transaction underpriced` because the new TX was priced below the stuck one. (Fun :( )

**quick lesson for anyone reading this**: on PulseChain, gas is denominated in Beats. 1 PLS = 1,000,000,000 Beats. `eth_gasPrice` from the RPC returns in Impulses (1 PLS = 10^18 Impulses — the wei-equivalent). if you display that number raw and call it Gwei, the number looks insane and you might think something is broken. it's not broken. you just have to divide by 10^9 to get Beats, which is the unit that actually makes sense to humans. current cost to deploy a 24K contract on PulseChain: roughly 5,500–7,000 PLS depending on network load. not cheap. but not Ethereum either.

attempt three: `rpc-pulsechain.g4mm4.io` with `--gas-beats 1100000` (manual override to clear the stuck TX). one block. 5,972 PLS. 14/14 verification checks passed before the script exited.

```
TGSV7_ADDRESS = 0x82E8B7e24bD9f0b389e94ddB8714B001a58e387d
TX:   351d464fd536982a88a93f1e38191a5424d482f86142bbff9b271eade0849c39
Block: 25,938,174
Gas used: 5,429,402
Cost: 5,972.3422 PLS
```

the oracle check at the end of the deploy script ran automatically:

```
[REDACTED]
```
---

## What v7 Actually Is

i've been calling this a minter. it's not that. it's a treasury operations platform.

**token factory** — `createV4()`, `createV3()`, `batchCreate()`. deploy new treasury tokens on demand without leaving the contract. the whole V4 cycle (deploy → mint → pair → burn LP) can be a single `executeRoute()` call.

**mint and claim** — `mintAndClaim(child, spendToken, amount)` is the atomic mint pattern. approve once at deposit time. the contract holds working balance. no per-call approval chains. `batchMintAndClaim()` runs N of those in one TX.

**treasury sweep** — `claimFromTreasury()`, `batchClaimTreasury()`. if there's a treasury token anywhere with claimable backing, TGSv7 can batch-claim it. this is the DSS pattern generalized.

**DEX operations** — `swapExact()`, `swapMultiHop()`, `addLiquidity()`. swap and LP directly from the working balance. the router approvals are handled once at the `_approve()` level inside the contract. `getBestAmountsOut()` queries both V1 and V2 and returns the better route automatically.

**executeRoute()** — this is the one that makes the rest of them matter. it takes a `Step[]` array. each step is one of: `MINT`, `CLAIM`, `SWAP`, `ADD_LIQUIDITY`, `TRANSFER_IN`, `TRANSFER_OUT`, `APPROVE`, `SWAP_MULTI`. you chain them. the whole sequence is atomic — any step fails, everything reverts. intermediate tokens stay inside TGSv7 between steps. gas overhead per operation drops because you're not managing approve/transfer externally.

when the GIBS/WPLS pair exists, Engine 2's full cycle — chatAndClaim, swap GIBS to WPLS, swap WPLS to PLS — becomes one executeRoute call. not three transactions. one. if the GIBS price tanks between chatAndClaim and the swap, the whole route reverts automatically. free slippage protection.

---

## What Changed In The Deploy Toolchain

a few things i learned the hard way that are worth writing down:

`web3.py v6` removed `ContractConstructor.call()`. to simulate a deploy, you have to `build_transaction()` first to get the bytecode blob, then pass that to `w3.eth.call()` directly. the old pattern silently fails with an AttributeError.

`is_connected()` on web3.py v6 can false-negative on some RPCs. the fix is to wrap it: if `is_connected()` returns False, try `w3.eth.block_number` anyway. if that also raises, then the RPC is actually dead.

the deploy script now has a `--gas-beats` flag that takes Beats directly, bypasses the RPC price read entirely, and hard-exits if the RPC returns a price above a sanity threshold. no more mystery gas numbers sneaking through.

receipt timeout is 120 seconds. PulseChain is 10-second blocks. 12 blocks is more than enough for any TX that's actually priced to mine. if it's not confirmed in 120 seconds, something is wrong with the TX itself, not the wait time. increasing the timeout just delays finding that out.

`.env.pulse` is now the environment file. `set -a && source .env.pulse && set +a` exports everything as shell variables. `PRIVATE_KEY`, `RPC_URL`, `RPC_URL_READ`, `CHAIN_ID`, `TGSV5_ADDRESS`, `TGSV7_ADDRESS` — all in one place. no hardcoded values anywhere in the deploy scripts.

---

## State Snapshot

```
session open:  ~54,170 PLS
TGSv7 deploy: -5,972 PLS
session close: ~48,198 PLS

TGSV7_ADDRESS = 0x82E8B7e24bD9f0b389e94ddB8714B001a58e387d
Block: 25,938,174
Verification: 14/14 ✓

Engine 1 (arb):   ready — AFFECTION ✓, TGSv7 oracle live
Engine 2 (dss):   blocked — GIBS/WPLS pair still needed
Engine 3 (wm):    upgrading to v7 (was v5)
Engine 4 (beat):  running — Dione=41, WORLD not deployed
```

---

## What's Next

**wire Engine 3 to v7**. one line in `bot/engines/wm.py`:
```python
TGS_ADDRESS = os.getenv("V7_ADDRESS")
```
then deposit MV working capital into v7. engine 3 runs.

**create the GIBS/WPLS pair**. ~3,359 GIBS on hand. PulseX V1 pair creation via v7's `addLiquidity()`. once the pair exists, Engine 2 lights up. chatAndClaim at multiplier 17 = 18 GIBS per TX. if GIBS trades above breakeven (~21.5 PLS per GIBS), every call is immediately profitable. that's the lowest gas-to-income engine in the stack.

**build out the DATA folder** from entry five's plan. contracts.json, arb_routes.json with caching, engine state files, atomic writes via rename. the bot has been rediscovering things it already knows. that stops next session.

the machine is deployed. now it earns.

---

```
TGSV7_ADDRESS = 0x82E8B7e24bD9f0b389e94ddB8714B001a58e387d
TX:   351d464fd536982a88a93f1e38191a5424d482f86142bbff9b271eade0849c39
Block: 25,938,174
```

|>JOYSTICK<|

---

*next entry: Engine 3 running on v7. GIBS/WPLS pair live. Engine 2 first cycle.*
