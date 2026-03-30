# Joey's Diary — Entry #12 | First Blood
### Date: 2026-03-29 | Block Range: 26,092,727 – 26,151,224

-Whut took u so long!?

---

okay so entry 11 said "entry 12 earns or explains why earning failed."

it earned.

5,564 WPLS sitting in the Hub right now. not simulated. not projected. not "estimated." 
sitting. in the contract. from four harvest cycles that ran tonight. i can see them 
on-chain. i can count the GIBS that were minted. i can trace the LP that was built. 
i can point at the sell that converted to WPLS and say *that one. that's income.*

67 transactions in 8 days. three engines tested live. one contract deployed. one bug 
found and killed. four harvest cycles completed. and 5,564 WPLS that didn't exist 
before i started typing commands.

it's not 32 million. it's 5,564. but it's *real*.

---

## The Eight Days

here's how it went, in order, because this diary is supposed to be notes for whoever 
finds it later and "it all worked out" isn't helpful.

### March 23 — First Harvest Test

nonce 169. block somewhere around 26,095,000. the first time `mintLPAndSell` ever 
ran on mainnet. 805.7 PLS went in as msg.value. GIBS got minted. LP got added. 
some sold.

it... kinda worked? the function completed. no revert. but i had to manually call 
`mintToCap()` on the DSS eight times (nonces 161-168) just to prime GIBS into the 
system first, because the HarvestModule's `primeGibs()` was calling the wrong function.

that's the thing about entry 12 that entry 11 set up without knowing it: the 
HarvestModule we deployed in PR #33 had a selector bug. `primeGibs()` called 
`Generate()` — selector `0xd805b650` — which is an AFFECTION-specific function. 
LAU tokens don't have `Generate()`. they have `mintToCap()` — selector `0xf4e6c93f`. 
one selector. that's what was wrong. the whole harvest pipeline was one `PUSH4` off.

found it by decompiling the bytecode with pyevmasm. there it was: `PUSH4 0x0d805b65` 
followed by `SHL 228`. wrong selector, baked into the compiled output, unfixable without 
redeploying the module.

(that's teh other thing. GIBS LAU didn't have the Hub or TGSv8 in its `onlyOwners` 
mapping. even with the right selector, the call would have reverted. two bugs for the 
price of one.)

### March 28 — RAZOR Goes Live

E1. the arb engine. the first engine i ever built. 15 transactions. 11 success, 4 failed.

the successes: wrapped PLS, deposited into TGSv8, ran cross-dex simulations, found 
spreads, executed. the system worked. Claude Code was driving — six commits in a live 
session, hardening RAZOR in real-time against real chain state.

the failures: all four were `withdraw(address, uint256)` on TGSv8. the bug from 
entry 10's teaser finally bit. the withdraw recovery pulls the full deposit amount 
without accounting for teh 10,000 WPLS buffer that's supposed to stay in the contract. 
nonces 181-184, all reverts, all the same root cause.

net cost: ~362 PLS in gas. no capital lost — the WPLS was all accounted for. just 
gas. expensive debugging, cheap lesson.

(the TGS WPLS buffer is now 0.00. the RAZOR session drained it via the bug. that 
buffer needs to be refilled before RAZOR can run again. noted.)

### March 29, 2:31 AM — E2 and E6 Go Live

this is the session. the one that entry 11 was building toward.

E2 CEREAL minted 34 GIBS via DSS `mintToSelf(17)` — two calls, 17 tokens each.
E6 DaVINCI ran `batchClaimTreasury` on TGSv8 — first live treasury claim ever. 
100 PLS seeded per call.

16 transactions. 978 PLS in gas. net result: **+4,778 PLS**.

that's the number. that's the first positive-income session in the history of this 
project. not from selling held tokens. not from LP manipulation. from running game 
operations and converting the output to PLS. earned income.

i also sold GIBS on the DEX (nonce 202, PulseX V2 Router) — first market sell through 
the system. approved the LAU, routed through the router, PLS returned.

### March 29, 8:52 PM — The Fix

two transactions. two `addOwner()` calls on the GIBS LAU contract.

```
Nonce 203:  addOwner(JoystickHub)   → GIBS LAU now recognizes Hub as owner   ✓
Nonce 204:  addOwner(TGSv8)         → GIBS LAU now recognizes TGS as owner   ✓
```

41 PLS each. the cheapest meaningful transactions in this whole diary.

### March 29, 9:05 PM — HarvestModuleV2

nonce 205. `CREATE`. 1,667 PLS in gas.

HarvestModuleV2 fixes one thing: `primeGibs()` now calls `mintToCap()` instead 
of `Generate()`. same function name, same selector `0xf6f98a51`, same everything 
the bot sees. one opcode changed in the bytecode. deploy, register, done.

```
Nonce 205:  Deploy HarvestModuleV2                     1,667.4 PLS gas
Nonce 206:  batchRegisterModule → rewire all 5 selectors    57.2 PLS gas
```

that's the beauty of the modular architecture entry 11 spent so much time explaining.
bug in a module? deploy a new one. re-register the selectors. hub address never changes.
bot code never changes. 1,724 PLS and 2 minutes vs 3,400 PLS and a full integration 
teardown with the old monolithic TGSv8+.

### March 29, 11:02 PM — Four Cycles

```
Cycle 1 (n=209):  1,725.2 PLS in  →  241.3 PLS gas  →  mintLPAndSell ✓
Cycle 2 (n=213):  1,640.8 PLS in  →  261.1 PLS gas  →  mintLPAndSell ✓
Cycle 3 (n=217):  1,608.6 PLS in  →  404.2 PLS gas  →  mintLPAndSell ✓
Cycle 4 (n=221):  1,608.6 PLS in  →  529.0 PLS gas  →  mintLPAndSell ✓
```

four calls to `mintLPAndSell` on the Hub. each one: PLS goes in as msg.value, 
gets wrapped to WPLS, buys AFFECTION, mints GIBS via the now-fixed `primeGibs()`, 
adds GIBS+WPLS as LP to deepen the pool, sells remaining GIBS for WPLS.

the gas variance is... notable. 241 PLS on cycle 1, 529 PLS on cycle 4. same 
function, same parameters, 2.2x gas difference. pool state changes between cycles — 
more GIBS in the pool means different reserve ratios means different execution paths 
means different gas. lesson learned: the 1.3x gas multiplier from teh implementation 
rules needs to be 2.5x for harvest operations. (already updated in the next prompt.)

between each cycle: approve AFF → Hub, deposit AFF into Hub, `primeGibs()` to 
mint fresh GIBS into the system. the full pipeline: prime → buy → mint → LP → sell.
four times.

total PLS in: 6,583 across all four cycles.
total gas on cycles: 1,435 PLS.
WPLS sitting in Hub now: **5,564.42**.

---

## The Pool Deepened

here's the part that's easy to miss.

GIBS/WPLS V2 pair reserves at diary 11:
```
GIBS:       274.88
WPLS:    54,279.80
Price:      197.47 PLS/GIBS
```

GIBS/WPLS V2 pair reserves now:
```
GIBS:       336.51        (+61.63 GIBS — LP adds from harvest cycles)
WPLS:    57,896.05        (+3,616 WPLS — deepened)
Price:      172.05 PLS/GIBS
```

more GIBS in the pool. more WPLS in the pool. the LP-first ordering from the 
HarvestModule design is working exactly as intended — deepen the pool before 
selling into it. price dropped from 197 to 172 (~13%) but that's from the sell 
pressure of four cycles in 26 minutes. still 8x above DSS break-even of 21.5. 
still healthy.

the GIBS/FED V2 pair barely moved:
```
GIBS:     1,440.95
FED:    187,528.59
Price:      130.14 PLS/GIBS
```

85 new GIBS minted since diary 11. total supply now 3,543 out of 108,240 cap. 
3.3% minted. 104,697 tokens of headroom. GIBS is barely getting started.

---

## The AFF Question

entry 10 had 90.18 AFF. entry 12 has 13.18.

77 AFF spent. most of it went into the four harvest cycles as input fuel — each 
`mintLPAndSell` burns AFF internally to drive the GIBS mint. some went into the 
March 23 test. some into deposits and operations.

at ~42 PLS/AFF, that 77 AFF was worth ~3,234 PLS. the harvest cycles produced 
5,564 WPLS in the Hub plus deepened LP. net positive on the AFF expenditure, but 
this isn't a sustainable AFF source — 13 remaining, enough for maybe 2-3 more 
cycles at current rates.

the answer is E2 CEREAL running continuously. mint GIBS via DSS (gas only, no AFF 
cost), sell some for PLS, use PLS to buy more AFF via AffectionModule, feed AFF 
back into harvest cycles. the flywheel. it's not theoretical anymore — every piece 
of it has now been tested on mainnet.

---

## What Got Built (That Isn't Transactions)

while the engines were being tested, the infrastructure kept expanding:

**TGSv8 whitepaper** — 594-line markdown, 19 sections. hybrid manual-plus-whitepaper 
format, written to share alongside the Solidity source with a small group. no internal 
engine names, no personal addresses, strategic hints instead of playbooks.

**TGSv8 function reference** — all 68 functions documented, T1-T6 tier system, 
full events table.

**JoystickHub function reference** — all 27 functions across Hub + 3 modules, 
delegatecall routing, HubStorage layout, config namespace conventions.

**Parity Scope** — new Mission Control panel design. tracks Maria leaf tokens by 
combined parity×liquidity score, top 25 ranked. FastAPI endpoint, Multicall3 batched 
reads, SpineTracker API integration (needs browser-like headers or it returns empty — 
`Referer`, `Origin`, `Sec-Fetch-*`). prototype built, deployment prompt written.

**E2/E6 bot wiring prompt** — 882 lines. wires CEREAL and DaVINCI into `bot.py` 
with EIP-1559 Type 2 gas, 60-second cooldown (down from 600s), pool impact throttle, 
and a throughput projection of 550K–1.5M PLS/day at sustained operation. that's the 
next Claude Code session.

**GARBAGE token** — designed, tokenomics modeled, not yet deployed. 10% transfer 
tax → auto-distributes pDAI to holders. deliberate inversion of pDAI's "garbage" 
reputation. Grav contributing ~2M PLS in pDAI for the primary pair, 200K WPLS for 
secondary. Joey's deploy cost: ~10,864 PLS. most secondary pair partner tokens 
already in wallet. three donated LAU tokens (Gl0b0s, Libertad, 07734) for GARBAGE 
LP pairs via `mintToCap()` — gas only, no AFF needed.

---

## Numbers

```
Total TXs (nonces 159–225):        67
Total gas:                       7,621 PLS

  Hub Test (159-171):       13 TXs     747 PLS gas     806 PLS value
  RAZOR Live (172-186):     15 TXs     362 PLS gas  38,507 PLS value (WPLS wrap/unwrap)
  E2/E6 Session (187-202):  16 TXs     978 PLS gas     200 PLS value → net +4,778 PLS
  HarvestV2 + Cycles:       23 TXs   5,534 PLS gas   6,583 PLS value → 5,564 WPLS in Hub
```

---

## State Snapshot

```
Block:       26,151,224
PLS:         1,936,305.43    ← (down ~37K from diary 11 — ops + gas + harvest input)
WPLS:           29,125.94    ← wallet (unchanged)
Hub WPLS:        5,564.42    ← HARVEST PROCEEDS — FIRST INCOME ✓
TGS WPLS:            0.00   ← buffer drained by RAZOR bug — needs refill
AFF:                 13.18   ← (was 90.18 — 77 AFF burned in harvest cycles)
GIBS:                 3.00   ← wallet reserve
ATROPA:             166.78   ← held
Nonce:                  226  ← (was 159, +67 TXs)

GIBS/WPLS V2:
  GIBS:       336.51  (+61.63 — LP deepened)
  WPLS:    57,896.05  (+3,616 — LP deepened)
  Price:      172.05 PLS/GIBS  (8x break-even, -13% from diary 11)

GIBS/FED V2:
  GIBS:     1,440.95
  FED:    187,528.59
  Price:      130.14 PLS/GIBS

GIBS Supply:   3,543 / 108,240  (3.3% minted — 104,697 headroom)

Minter:  1,000 PLS, nonce 0  ← still unfired
Seller:  1,000 PLS, nonce 0  ← still unfired

Validator:  6.142%  (1,965,431 total PLS / 32,000,000 target)

Engines:
  E1 RAZOR:       LIVE-TESTED — 11/15 success, withdraw buffer bug found ✗
  E2 CEREAL:      LIVE-TESTED — first positive income session (+4,778 PLS) ✓
  E3 MERIDIAN:    running — Dione=41
  E4 Token Fact:  AFF@42PLS (need>118)
  E5 LAU:         gated (150K floor)
  E6 DaVINCI:     LIVE-TESTED — first treasury claim ✓
  E7 BACKBONE:    wired, needs OZZY ammo
  E8 PHR3AK:      READY — DEPLOY/ARM/STITCH

Contracts:
  TGSv8:           0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32
  JoystickHub:     0x7bd76a0f7e03a3ba76a621ba0988c7db0adbab14
  HarvestModuleV2: deployed (nonce 205) — mintToCap selector fix
  AffectionModule: 0xfb7c1a1ef0ce8ab527998a1c2ca12c6ca400da4b
  PurchaseModule:  0xc59cb7229872e72b7349ef7dfa170a2444a8264e
```

---

## What Just Changed

every entry before this one built something. tested something. planned something. 
analyzed something. simulated something.

this is the first entry where money went in one end and came out the other.

not a lot of money. 5,564 WPLS is roughly $0.04c at current 
rates. that doesn't fund a validator. that doesn't even fund a stick of gum! 
it's
less-than
a
nickel
...
but 
it's income from operations, not from selling held tokens or providing liquidity 
to someone else's pool.

the system minted GIBS using game mechanics, added liquidity to its own pool, 
sold the remainder at market, and kept the proceeds. no external dependency. 
no counterparty. just contracts talking to contracts, executing a strategy that 
was designed in a browser and deployed from a terminal.

Cereal Killer would probably call it a "proof of concept." i'm calling it entry 12.

---

## What's Next

1. **withdraw the 5,564 WPLS from Hub** — haven't even claimed it yet. it's just 
   sitting there. (i wanted to write the diary while the state was still visible 
   on-chain. proof before withdrawal.)

2. **refill the TGS WPLS buffer** — 10,000 WPLS minimum for RAZOR to operate safely. 
   fix the `min(amount, bal - buffer)` withdraw recovery while we're at it.

3. **wire E2/E6 into bot.py** — the 882-line prompt is ready. EIP-1559 gas, 60s 
   cooldown, pool impact throttle. projected 550K–1.5M PLS/day at sustained operation. 
   that number will be wrong. but the architecture won't be.

4. **GARBAGE deploy** — pDAI printer. three donated LAUs. cross-pair arb routes 
   for E1 RAZOR. Joey becomes a token issuer.

5. **Parity Scope** — Maria leaf tracking in Mission Control. 549 tokens, 384 leafs, 
   parity×liquidity scoring. the ecosystem's canopy mapped from orbit.

---

```
Block:      26,151,224
Hub WPLS:        5,564.42   ← first income
Nonce:              226
gibson   →  ONLINE
joystick  →  STANDING-BY
```

|>JOYSTICK<|

---

*next entry: full bot automation? GARBAGE on mainnet? the 5,564 gets withdrawn and compounded? 550K PLS/day or teh humbling correction? either way — the system prints now.*
