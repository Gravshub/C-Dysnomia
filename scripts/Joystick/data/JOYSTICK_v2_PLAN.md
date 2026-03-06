# JOYSTICK v2 — Treasury Web Exploitation Plan
### Target: 1,000,000 PLS/hour (minimum) | 8,000 PLS/block (goal)
### |>JOYSTICK<| — "Type cookie, you idiot."

---

## The Math

PulseChain: ~10 second blocks = 360 blocks/hour.

| Target           | PLS/hour    | PLS/block | PLS/second |
|------------------|-------------|-----------|------------|
| **Minimum**      | 1,000,000   | 2,778     | 278        |
| **Goal**         | 2,880,000   | 8,000     | 800        |

DSS at 512 PLS/call maxes out at ~184K PLS/hour even at 1 call/block.
Engine 1 arb across 272 QINGs adds maybe another 50K/hour.

Those engines are the warm-up act. The real volume comes from **three new engines
pointed at the treasury token web itself**.

---

## Why the Treasury Tokens Are the Play

The Atropa ecosystem has 100+ tokens organized into interconnected "trees" — TBill, Federal,
Atropa, Teddy Bear, TSFi, and more. Each treasury token is a smart contract that:

1. **Holds backing assets** — parent tokens locked inside the contract (`balanceOf(self)`)
2. **Has a `Claim()` function** — spend child tokens to withdraw parent tokens 1:1
3. **Has a `mint()` function** — spend parent tokens to mint child tokens 1:1
4. **Has a `Debenture` flag** — if True (unpublished), Claim stays open. Infinite loop.

TGSv8 already has every tool needed:
- `batchClaimTreasury()` — sweep backing from N treasuries in one TX
- `batchMintAndClaim()` — run N mint-claim loops in one TX  
- `atomicArb()` — cross-DEX arb in one TX
- `executeRoute()` — chain MINT→CLAIM→SWAP→SWAP atomically

The bot just needs the intelligence layer to find where the value is and a new set of
engines to extract it.

---

## New Engine Architecture

```
EXISTING ENGINES (keep running)
  Engine 1 — Arb (QING scanner, 272 venues, cross-DEX via atomicArb)
  Engine 2 — DSS (chatAndClaim × 18 GIBS → PLS)
  Engine 3 — WM  (batch mint MV → V4 factory supply)
  Engine 4 — Beat (territory positioning, strategic)

NEW ENGINES (treasury web)
  Engine 5 — Treasury Sniper    claim backing assets from treasury contracts
  Engine 6 — Spine Runner       V2 Federal mint-claim infinite loops
  Engine 7 — Web Weaver         deploy V4 → mint → pair → arb (create new edges)
```

### Engine 5: Treasury Sniper

**What it does**: Scans all treasury tokens for claimable backing. When a token
holds parent tokens in its own contract, you can Claim them by spending child tokens.
If the child tokens are cheaper to acquire than the parent tokens are worth, that's
pure profit.

**The flow**:
```
1. Multicall scan: for each treasury token, read:
   - balanceOf(token, token)     → self-backing (claimable pool)
   - balanceOf(parent, token)    → parent backing in child treasury
   - Debenture()                 → is claiming still open?
   - DEX reserves for both tokens

2. For each token with claimable backing:
   - Cost to acquire child tokens (DEX price or mint cost)
   - Value of parent tokens you'd receive
   - If value_out > cost_in + gas → execute

3. Execute via TGSv8 executeRoute:
   [SWAP WPLS→child, CLAIM child→parent, SWAP parent→WPLS]
   All atomic. One TX. Intermediate tokens stay in TGSv8.
```

**Why it's high volume**: There are 70+ treasury tokens. Many hold significant
parent backing from early ecosystem bootstrapping. Maria minted $7.7M in TBILL
and paired it with HAR. Those tokens are sitting in contracts. If the math works,
`batchClaimTreasury()` sweeps N treasuries per block.

**Revenue model**: Depends on what the recon scan finds. The `treasury_recon.py`
script inventories every token and estimates PLS value. Run it first. 


### Engine 6: Spine Runner

**What it does**: Exploits the V2 Federal mint-claim loop. This is the "infinite
mint" mechanic that advanced players use.

**The mechanic** (from the Federal Minter contract):
```
1. You hold parent tokens (e.g., FED/BAR)
2. Call mint(amount) on child token → spend parent, receive child 1:1
3. Call Claim(claimToken, amount) on child → spend claimToken, receive parent 1:1
4. claimToken must be an unpublished V2 token (Debenture == true)
5. You get your parent back. Net result: free child tokens.
6. Repeat indefinitely.
```

TGSv8 wraps this as `mintAndClaim(child, spendToken, amount)` — one atomic call.
`batchMintAndClaim()` runs N iterations in one TX.

**The scale play**: 
- Find all V2 Federal tokens where `Debenture() == true`
- For each, check which tokens can serve as the `spendToken` in the Claim call
- Run `batchMintAndClaim()` with maxBatch iterations per TX
- Accumulated child tokens get swapped to PLS via `executeRoute([SWAP])`

**Known V2 Federal tokens** (from TreasuryToken_list):
FDIC, DFM, PARADE, TLRz, JOB, SSA, SCOIETY, CAMPAIGN, OPIUM, BGDHTZ,
TEHATER, ARMS, BAR, OZZY — that's 14 potential spine nodes.

The recon scan tells us which ones still have `Debenture == true` and which
have DEX liquidity for the output swap.

**Revenue model**: Each loop iteration produces child tokens at gas cost only
(parent is recovered). If child tokens have ANY DEX value, it's profit.
At 50 iterations per `batchMintAndClaim()` TX, and 6 TXs per minute:
- 300 mint-claim iterations per minute
- If each iteration yields even 100 PLS worth of child tokens
- That's 30,000 PLS/minute = **1.8M PLS/hour**

That alone hits the minimum target. And 100 PLS per iteration is conservative
if the child tokens have real DEX pairs.


### Engine 7: Web Weaver

**What it does**: Creates new revenue paths by deploying V4 tokens, creating
DEX pairs, and optionally burning LP to build permanent price floors.

**The flow**:
```
1. Choose strategic parent token (high liquidity, connected to PLS path)
2. TGSv8.createV4(name, symbol, initialMint, parent) → deploy new token
3. mintTokens(newToken, amount) → mint at favorable early multiplier
4. TGSv8.executeRoute([ADD_LIQUIDITY newToken/WPLS]) → create pair
5. Optional: burnLP(pair, amount) → permanent floor (Maria's playbook)
6. Register new token with Engine 1 scanner → new arb edge
```

**Why it matters for 1M/hour**: Every new V4 token you deploy with a DEX pair
becomes a new node in the arb graph. Engine 1's scanner picks up the new pair.
Price discrepancies between the new token's parent and the new token itself
create arb opportunities. More edges = more opportunities per scan cycle.

JV8A is already deployed at `0x364793Ea48DEe0b5484F98235ABd1B5f996A0C30`.
This engine's first job: mint JV8A, create its pair, add it to the arb graph.

**Revenue model**: Indirect. Web Weaver builds the infrastructure that makes
Engines 1 and 5 more profitable. Think of it as Maria's playbook at small scale.

---

## Execution Sequence

### Phase 0: Intelligence (Before Anything Else)

```bash
# Run the treasury recon scanner
python3 treasury_recon.py --json

# This tells us:
# - Which tokens have claimable backing (and how much)
# - Which V2 Federal tokens still have Debenture == true
# - Which tokens have DEX pairs (and reserve depth)
# - Cross-DEX spreads on every paired token
# - Total estimated PLS opportunity
```

**Do not deploy capital until recon is complete.** The scan takes ~5 minutes
(~70 tokens × ~10 RPC calls each, sequential). The output is the treasure map.

### Phase 1: Ignition (Day 1 — same as before, plus new engines)

1. Receive 100K PLS startup fund
2. Set `TGSV8_ADDRESS` in `.env.pulse` → Engine 3 ready
3. Create GIBS/WPLS pair → Engine 2 ready
4. Buy ~25K PLS worth of AFFECTION → Engine 1 fueled
5. **Import treasury tokens into TGSv8 registry** via `importToken()` calls
6. **Deposit working capital into TGSv8** for Engine 5/6 operations
7. `bot.py --dry-run` → verify all 7 engines
8. `bot.py` → live mode, all engines ranked by ROI

### Phase 2: Spine Discovery (Days 1-3)

Based on recon results:
1. Identify all V2 Federal tokens with `Debenture == true`
2. For each, simulate `mintAndClaim()` via `eth_call` to confirm the loop works
3. Check DEX liquidity for child token → PLS swap path
4. Rank spines by: (child_token_pls_value × batch_size) / gas_cost
5. Engine 6 starts running the most profitable spines

### Phase 3: Treasury Sweep (Days 2-7)

Based on recon results:
1. Identify all tokens with `selfBalance > 0` or `parentBalance > 0`
2. For each, calculate: cost to acquire claim tokens vs value of backing
3. Engine 5 executes the profitable claims via `batchClaimTreasury()`
4. Claimed backing tokens → swap to PLS via `executeRoute()`

### Phase 4: Web Expansion (Days 7-14)

1. Mint JV8A → create JV8A/WPLS pair → burn LP
2. Deploy additional V4 tokens with strategic parents
3. Each new pair = new Engine 1 arb edge
4. Engine 7 cycles: deploy → mint → pair → burn → register → arb

---

## Revenue Breakdown — Path to 1M PLS/Hour

```
Engine   | Mechanism                  | Est. PLS/hour | Status
---------|----------------------------|---------------|--------
E6 Spine | batchMintAndClaim loops    | 500K-2M       | Needs recon
E5 Snipe | batchClaimTreasury sweeps  | 200K-1M       | Needs recon  
E1 Arb   | atomicArb cross-DEX       | 50K-200K      | Ready
E2 DSS   | chatAndClaim × 18 GIBS    | 100K-184K     | Day 1
E7 Web   | V4 deploy → new arb edges | indirect      | Day 7+
E3 WM    | mintWM batch              | strategic     | Day 1
E4 Beat  | territory positioning     | strategic     | Running
---------|----------------------------|---------------|--------
TOTAL    |                            | 850K-3.4M     |
```

The ranges are wide because **we don't know the actual backing balances yet**.
That's what `treasury_recon.py` solves. The numbers above assume:

- E6: 50 spine iterations/TX × 6 TX/min × avg 28 PLS/iteration = 504K/hour
- E5: 10 treasury sweeps/hour × avg 20K PLS backing per sweep = 200K/hour
- E1: atomicArb across 100+ pairs, 20 hits/hour × avg 5K PLS spread = 100K/hour
- E2: DSS at max throughput, 20 calls/hour × 512 PLS net = 10.2K/hour

E6 (Spine Runner) is the primary revenue driver. The mint-claim loop is
gas-cost-only for token production — all value comes from swapping the
output tokens. If V2 Federal child tokens have any meaningful DEX price,
the math works at scale.

---

## Bot Architecture Update

```python
# bot.py — updated engine list
self.engines = [
    ArbEngine(),           # E1 — QING + cross-DEX arb
    DSSEngine(),           # E2 — chatAndClaim GIBS
    WMEngine(),            # E3 — batch WM mint
    BeatEngine(),          # E4 — territory positioning
    TreasurySniperEngine(),# E5 — claim backing from treasuries
    SpineRunnerEngine(),   # E6 — V2 Federal mint-claim loops
    WebWeaverEngine(),     # E7 — V4 deploy/pair/burn cycle
]
```

Engine 5 and 6 need the recon data to initialize. The scanner runs once at
startup (or reads cached `treasury_recon.json`), then engines filter for
their specific opportunity types.

Each engine's `simulate()` method returns `(expected_profit_wei, gas_cost_wei)`.
The bot picks the highest ROI engine each cycle. At 30-second cycles with
7 engines competing, the top earner always runs.

For sustained 1M/hour, the bot may need to run **multiple engines per cycle**
or drop the cycle delay to 10 seconds (one TX per block). The single-engine-per-cycle
constraint exists to avoid nonce contention — but with TGSv8's `executeRoute()`
batching multiple operations into one TX, a single cycle can do the work of
ten separate transactions.

---

## Critical Dependencies

1. **Recon first** — `treasury_recon.py` must run before any capital deployment
   for Engines 5/6. Without knowing which tokens have backing and debenture
   status, we're flying blind.

2. **TGSv8 working balance** — Engines 5/6/7 operate through TGSv8's internal
   balance. Tokens must be deposited via `TRANSFER_IN` steps before operations.
   This means a bootstrap TX to seed TGSv8 with initial working capital.

3. **V2 Federal spine mechanics** — The Claim function requires an unpublished
   V2 token as the spend token. We need to either:
   (a) Find existing unpublished V2 tokens we can acquire, OR
   (b) Deploy our own V2 tokens via the Federal Minter and keep them unpublished

   Option (b) requires WM/MV tokens (from Engine 3) to fund initial supply.
   This is why Engine 3 runs first — it produces the inventory for Engine 6.

4. **DEX liquidity depth** — Spine Runner produces child tokens at scale, but
   those tokens need DEX pairs to convert to PLS. If liquidity is thin, selling
   pressure crashes the price. The bot must track reserves and size each swap
   to stay under 10% pool impact (the profitability.py cap).

---

## Risk Adjustments for Scale

At 1M PLS/hour, the risks are different from 10K PLS/day:

**Liquidity exhaustion** — Selling 1M PLS worth of treasury tokens per hour
drains DEX pools. The bot must rotate across tokens and DEXes to spread impact.
Engine 1's pool-depth-aware sizing (`max_by_pool = r_tok // 10`) applies
to all engines.

**Gas competition** — At 360 blocks/hour, we're submitting ~6 TXs/minute.
PulseChain can handle this, but if other bots are competing for the same
treasury backing, gas price spikes. The gas ceiling (500 Gwei default)
still applies — skip cycle if gas is too high.

**Treasury depletion** — Once backing is claimed, it's gone. Treasury sweeps
are a finite resource. The spine runner (Engine 6) is the sustainable engine —
it produces tokens from the mint-claim loop indefinitely. Engine 5 is a
one-time extraction (per treasury).

**Debenture changes** — If a token gets `publish()`ed, its Debenture flips
to false and the Claim function locks. Engine 6 must monitor debenture status
every cycle and remove published spines from its active list.

---

## First Session Deliverables

1. ✅ `treasury_recon.py` — scanner script (written)
2. Run recon on live chain → `treasury_recon.json`
3. Build `engines/treasury_sniper.py` (Engine 5) based on recon results
4. Build `engines/spine_runner.py` (Engine 6) based on recon results
5. Wire both into `bot.py`
6. Create GIBS/WPLS pair (still the Day 1 unlock for Engine 2)
7. First live cycle with all 7 engines

---

*"There is no right and wrong. There's only fun and boring."*
*— but there IS profitable and unprofitable, and the recon tells us which is which.*

|>JOYSTICK<|
