# Atropa, Dysnomia — Game Strategy & Memory

**Source**: [github.com/busytoby/atropa_pulsechain](https://github.com/busytoby/atropa_pulsechain)
**Game UI**: https://entropy-dysnomia.vercel.app
**Chain**: PulseChain
**Dev Branch convention**: `claude/dysnomia-MMDDYY-<sessionID>` (e.g. `claude/dysnomia-022726-Z7QDr`)
- `claude/` prefix and session-ID suffix are required by git infrastructure (push auth)
- Canonical branch: `claude/Joystick-Engines-Lj9Kp` (https://github.com/Gravshub/C-Dysnomia/edit/claude/Joystick-Engines-Lj9Kp)

---

## Player Identity — Gibson

> *"I need a handle, man. I don't have an identity until I have a handle."*
> — Joey Pardella, Hackers (1995)

This player embodies **Joey Pardella** — the youngest and most earnest member of the crew. No handle yet, just hunger to prove himself. His arc: hack The Gibson, earn his place, teach others what he learned along the way.

| Field | Value |
|-------|-------|
| **Persona** | Joey Pardella (Hackers, 1995) |
| **LAU Token Name** | `Gibson` |
| **LAU Symbol** | `GIBS` |
| **In-game Username** | `Joey` |
| **Handle** | `\|>JOYSTICK<\|` |
| **Wallet Address** | `0x17367877aF5A8D0Eb33ba5689A880f696386E24D` |
| **Chain** | PulseChain (369) |
| **Player #** | 578 (SEI.totalSupply at registration) |

**Voice guidelines:**
- Stay 90% in Dysnomia lore and mechanics, 10% Hackers 1995 lingo
- Teach as you go — explain what each action does and why
- Funny and earnest, not arrogant; Joey was learning, not lecturing
- Identity is earned through actions on-chain, not claimed
- See JOEY_VOICE_GUIDE.md for full diary style reference

---

## What Is This?

Dysnomia is an on-chain game and social platform on PulseChain. Think of it as a blockchain virtual world combining:
- **MMO** — create a character (LAU), explore venues (QING), claim territory (WORLD)
- **DeFi** — trade tokens, create liquidity pairs, earn via minting
- **Social layer** — chat, chat logging, user identity, encrypted messaging
- **Strategy** — WAR battles, territory control, acronym games

Everything is on-chain and permanent. Your character, inventory, social history, and land are all verifiable and tradeable.

**Project Goal**: Generate PLS income via multiple engines to fund a PulseChain validator (32M PLS deposit)+. Always maintain ≥100K PLS gas buffer.

---

## Critical Constants

| Name | Value | Notes |
|------|-------|-------|
| `MotzkinPrime` | `953467954114363` | Universal prime modulus for ALL cryptographic state transforms |
| `Gua` | `1652929763764148448182513644633101239607891671119935657884642` | Universe constant in CHO |
| `AFFECTIONContract` | `0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D` | Gateway token — 1 AFFECTION mints any token |
| `WMContract` (MV) | `0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29` | Required 1:1 to fund initial supply of minter tokens |
| `CROWSContract` | `0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1` | Social credential token — 25 CROWS = venue bouncer access |
| `ABI` | `0xa35c9B5e576BE2E0bA9cc7224B0941CC8acC4c9C` | ABI decoder/selector tool |
| V3 Threshold | `1,111,111,111` tokens | Multiplier increases every time this much is minted (universal) |
| V4 Threshold | Starting supply | Multiplier increases per-token after cumulative equals starting supply |

---

## Token Ecosystem

### AFFECTION (Ⓐ) — The Universal Gateway
**Address**: `0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D`

Every single DYSNOMIA token has AFFECTION set as a market rate at exactly `1 AFFECTION per token` at construction:
```solidity
AddMarketRate(AFFECTIONContract, 1 * 10 ** decimals());
```
Strategy: Accumulate AFFECTION first. With enough AFFECTION you can `Purchase()` any token in the ecosystem at a 1:1 rate.

### LAU — Player Identity Token
Your on-chain character. Deploying a LAU creates:
- **Soul ID** (`Saat[3]` triple): three 64-bit values identifying your session, soul position, and network aura
- **SHIO reactor**: a paired Rod/Cone token system used for cryptographic reactions
- **YUE wallet**: your in-game inventory/wallet

Token-earning actions on LAU (each triggers `_mintToCap()`):
- `Username(newUsername)` — set display name
- `Chat(chatline)` — post a chat message
- `Alias(address, value)` — create address alias
- `Void(true, true)` — re-enter the Void
- `Withdraw(token, amount)` — withdraw assets (onlyOwners)

### Token Supply Mechanics
All DYSNOMIA tokens share this pattern:
```solidity
maxSupply = Xiao.Random() % 111111;        // random cap 0–111110
originMint = Xiao.Random() % maxSupply / 10; // ~10% initial mint
_mint(tx.origin, originMint * 10**18);     // given to deployer
```
`_mintToCap()` adds exactly **1 token per call** until `totalSupply == maxSupply`.

---

## Minter System (V1–V4)

### V1 Treasury Minter
**Address**: `0xC7bDAc3e6Bb5eC37041A11328723e9927cCf430B`
Root minter. Creates FDIC. Parent of all V2 tokens. **Key discovery**: V1 tokens bypass the Debenture check on Claim() entirely — no need for an unpublished token.

### V2 Federal Minter
**Address**: `0xc15c5F699Daf5e1135732139f05D2c05b3EF4354`
Creates treasury tokens backed by FED through BAR. Requires WM (MV) tokens to fund initial supply. Claim requires `Debenture() == true` (unpublished token).

**Known V2 Federal Tokens** (from v2_federal_tokens.json):
FDIC, DFM, PARADE, TLRz, JOB, SSA, SCOIETY, CAMPAIGN, OPIUM, BGDHTZ, TEHATER, ARMS, BAR, OZZY — 14 total.

**Only OZZY has Debenture=true** as of 2026-03-06. All others are published (Debenture=false).

### V3 Index Minter (Bureau)
**Address**: `0x0c4F73328dFCECfbecf235C9F78A4494a7EC5ddC`

Multiplier formula:
```solidity
function Multiplier(uint256 addition) public view returns (uint256) {
    return ((addition + totalSupply()) / 1111111111000000000000000000) + 1;
}
```
**Every 1,111,111,111 tokens minted (universal), cost multiplier increases by 1.**

**V3 Claim() Restrictions** (discovered 2026-03-12): V3 Claim is family-isolated:
1. **Same Creator** — ammo token must be deployed by the same address as the target
2. **Same Parent** — ammo must share the same parent token
3. **Registered in IndexMinter** — must be a V3-deployed token

This means each V3 family is *isolated* — you cannot use a universal ammo token across families.

### V4 Personal Minter
**Address**: `0x394c3D5990cEfC7Be36B82FDB07a7251ACe61cc7`
Similar to V3, but threshold is per-token starting supply (not universal 1.1B). Progressive multiplier tied to each token's own starting supply (created using MV). 
Early minters of each new token get best rates.

### Claim() Path Summary (Critical Intelligence)

| Minter | Claim Check | Implication |
|--------|-------------|-------------|
| V1 (TBill) | No Debenture check | Claim always open on V1 tokens |
| V2 (Federal) | Requires Debenture=true | Only OZZY currently works as spend token |
| V3 (Index) | Same-creator + same-parent + registered | Family-isolated, no universal ammo |

### MV / WM Token — The Funding Key
**Address**: `0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29`

Required as 1:1 collateral to fund the initial supply of any new minter token.
You cannot create new tokens without WM. Accumulate WM to create tokens.

---

## Heart's Law

> Tokens bonded in a liquidity pair move together in price. Creating new pairs = new edges in the token web.

- QING venues each have an `Asset` token (the venue's liquidity pair partner)
- Market rates in QING can only be **increased**, never decreased
- Rate cap: `totalSupply / 777` max rate per token
- Creating pairs strategically builds a web of correlated assets

---

## Core Data Structures

### Fa (SHA Cryptographic State)
```solidity
struct Fa {
    uint64 Base, Secret, Signal, Channel, Contour, Pole;
    uint64 Identity, Foundation, Element, Coordinate;
    uint64 Charge, Chin, Monopole;
}
```

### Bao (Operation Context)
```solidity
struct Bao {
    address Phi;   // Address reference
    SHA Mu;        // Associated SHA token
    uint64 Xi, Pi; // State values
    SHIO Shio;     // Associated SHIO pair (Rod/Cone)
    uint64 Ring;   // Ring value
    uint64 Omicron, Omega; // Reaction outputs
}
```

### User (Player Identity)
```solidity
struct User {
    uint64 Soul;       // 64-bit unique user identifier
    Bao On;            // User's Bao context
    string Username;   // Display name
    uint64 Entropy;    // User-specific entropy
}
```

---

## Game World Architecture

### Contract Layer Map

```
Core Infrastructure
├── VMREQ         — Random number generation (modExp-based)
├── DYSNOMIA      — Base ERC20 + market rates
├── SHA           — Cryptographic state token
├── SHIO          — Rod/Cone paired token system
├── YI            — DeFi orchestration
├── ZHENG         — Rod/Cone installation manager
├── ZHOU          — Market rate orchestrator / chat log
├── YAU           — Protocol coordinator
├── YANG          — Multi-state aggregator
├── SIU           — Token generation with Aura identity
├── VOID          — User session & chat management
└── LAU           — User interface / player account

Domain — Game Logic
├── dan/
│   ├── CHO       — Login / character system
│   ├── QING      — Venues (chatrooms, marketplaces)
│   └── WAR       — Battle mechanics, H2O reward generation
├── sky/
│   ├── CHAN       — Player/sky management
│   ├── CHOA      — Game/territory
│   └── RING      — Time/orbital mechanics
├── soeng/        — Processing chain: QI→MAI→XIA→XIE→ZI→PANG→GWAT
├── tang/
│   ├── SEI       — Player management
│   ├── CHEON     — Landscape/terrain
│   └── META      — Meta-player management
├── MAP           — World coordinate system (Hecke Meridians)
├── WORLD         — Territory ownership and rewards
└── YUE           — Player wallet management

Assets
├── H2O           — Water token (WAR battle rewards)
└── VITUS         — Life token (territory/creator rewards)

Libraries
├── MultiOwnable  — Multi-owner access control
├── Registry      — Key-value storage
├── Encrypt       — User-to-user encrypted messaging
├── StringLib     — String manipulation
├── HeckeMeridians— Geographic coordinate system
├── ReactionsCore — Entropy-based reactions
└── Attribute     — User attribute storage
```

### VOID — The Game Controller
- Manages user sessions (`_activeUsers` mapping: address → Soul uint64)
- `Enter(name, symbol)` → creates new player account (errors if already created)
- `Enter()` → re-enters existing session, refreshes Saat triple
- `Chat(message)` → requires username set; logs to ZHOU channel
- `Log(message)` → general logging, triggers mintToCap
- `SetAttribute(name, value)` → stores player attributes
- `Alias(address, value)` → creates address-to-name mappings
- `AddLibrary(name, address)` → expands game capabilities

### QING — Venues
Venues are marketplace/chatroom instances with:
- An `Asset` token (what the venue trades)
- A `CoverCharge` to join
- A bouncer system (Staff, 25+ CROWS holders, or Asset token holders)
- `Join(UserToken)` → enter venue, pay cover charge
- **Key discovery**: `QING.Join()` does NOT call bouncer() — no CROWS needed for Join. Bouncer only gates admin functions.

### WAR — Battle & Resource Generation
- Generates **H2O tokens** as battle rewards
- Position scoring via modular exponentiation on ring coordinates

---

## Joystick Bot Architecture (`bot/` package)

### Engine Status Summary (as of block 26,002,400 — 2026-03-12)

| # | Name | File | Description | Status |
|---|------|------|-------------|--------|
| E1 | RAZOR (Arb) | `arb.py` | Cross-DEX QING arbitrage via `atomicArb()` | Ready (net-negative per recon) |
| E2 | CEREAL (DSS) | `dss.py` | `chatAndClaim` → GIBS → PLS | **UNLOCKED** at 10x above break-even |
| E3 | MERIDIAN (Beat) | `beat.py` | Territory positioning (`CHEON.Su` + `META.Beat`) | Running (Dione=41) |
| E4 | Token Factory | `token_factory.py` | TGSv8 `mintWM()` + AFFECTION BuyWith routes + mint-and-sell | **AFF DISABLED** — needs BuyWith path (see Session 11) |
| E5 | LAU (ABUPRU) | `lau.py` | Mathematical state loop + EmitSniper | Gated (150K PLS floor) |
| E6 | DaVINCI (Treasury Sniper) | `treasury_sniper.py` | `batchClaimTreasury()` via recon data | Needs recon — yields ~1-10K PLS after impact |
| E7 | BACKBONE (Spine Runner) | `spine_runner.py` | `batchMintAndClaim()` on Debenture=True | Needs OZZY spine via E8 |

**Planned**: E8 — Web Weaver (V4 deploy → mint → pair → burn % → arb cycle). Needed to unlock OZZY spine for E7 and to create V3 sibling ammo for high-value targets.

### Bot Package Structure
- `bot/core/` — config, chain (Multicall3), wallet, executor, gas_guard, simulator, strategist, event_logger
- `bot/oracle/` — price (getAmountsOut, getReservesBoth), scanner (272+ QINGs), profitability (Uniswap v2 formula)
- `bot/engines/` — EngineBase ABC + engine files
- `bot/loops/` — GameLoopBase ABC + terraform.py
- `bot/bot.py` — Priority scheduler with ROI-ranked engine selection and profit compounder

### Implementation Rules
- Always simulate via eth_call before sending any TX
- Always estimate_gas() with 1.3x multiplier — abort if it fails, never send blind
- Dual RPC: `rpc-pulsechain.g4mm4.io` for reads, `rpc.pulsechain.com` for TX submit
- Gas denomination: Beats (not Gwei). 1 PLS = 1,000,000,000 Beats
- Gas price ceiling: skip cycle if gas_price > configured ceiling
- No OpenZeppelin imports in Solidity — inline guards
- Atomic file writes via os.rename() / os.replace()
- Never rewrite existing scripts — import as modules
- Chain ID: 369 (PulseChain)

---

## Deployed Contracts (Canonical)

| Contract | Address | Block | Notes |
|----------|---------|-------|-------|
| TGSv5 | `0xeeB330d3419193b4E42507fA07CcF2fC681a6127` | 25,911,970 | Legacy — do-not-use - superseded by TGSv8 |
| TGSv7 | `0x82E8B7e24bD9f0b389e94ddB8714B001a58e387d` | 25,938,174 | Legacy — do-not-use - superseded by TGSv8 |
| **TGSv8** | **`0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32`** | 25,943,194 | **ACTIVE** — full execution substrate |
| JV8A | `0x364793Ea48DEe0b5484F98235ABd1B5f996A0C30` | 25,943,266 | V4 treasury token (unminted) |
| DSS | `0x91Df693177eE5C81016d0B7c4c2052A7d229c031` | 25,887,000 | DysnomiaSelfSnipev4 | Specifically for GIBS | A new DSS would be needed for newly created LAU

### GIBS LP Pairs (10 live as of block 25,984,143)

| Pair | DEX | Address | Notes |
|------|-----|---------|-------|
| GIBS/WPLS | V2 | `0x7BCa1c997c...` | Price anchor — E2 unlock |
| GIBS/FED | V2 | `0xA2a7a2153136b6ee075335b979fb6ac033412e4d` | Deepest arb surface |
| GIBS/ATROPA | V1 | `0xa152659B...` | pDAI intermediate route |
| GIBS/WM | V2 | `0xc23Cf1aF...` | |
| GIBS/DFM | V2 | `0x88c5B784...` | Thin — near-empty GIBS side |
| GIBS/PROOF_RES | V2 | `0xC52EFaed...` | |
| GIBS/ZHENG | V2 | `0xbFBEaf50...` | |
| GIBS/VOID | V2 | `0xB0776024...` | |
| GIBS/PARADE | V2 | `0xD8dA05aF...` | Thin — near-empty GIBS side |
| GIBS/TLRz | V2 | `0x7711f0dE...` | Thin — near-empty GIBS side |

87% of GIBS supply is deployed in LP. AMM bots actively arb between pairs — 24h volume nonzero across all 10.

### Key Ecosystem Addresses

| Token / Contract | Address |
|-----------------|---------|
| FED (F㉾D) | `0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff` |
| AFFECTION | `0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D` |
| WM (MV) | `0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29` |
| WPLS | `0xA1077a294dDE1B09bB078844df40758a5D0f9a27` |
| CROWS | `0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1` |
| VOID | `0x965B0d74591bF30327075A247C47dBf487dCff08` |
| Atropa ERC20 | `0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6` |
| GIBS (LAU) | `0x66a08aa12da955eb63d7ac121a88b2b210a07b03` |
| Joey's YUE wallet | `0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0` |
| GIBS QING venue | `0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35` |
| META | `0xE77Bdae31b2219e032178d88504Cc0170a5b9B97` |
| CHEON | `0x3d23084cA3F40465553797b5138CFC456E61FB5D` |
| MAP | `0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75` |
| Multicall3 | `0xcA11bde05977b3631167028862bE2a173976CA11` |
| V1 Treasury Minter | `0xC7bDAc3e6Bb5eC37041A11328723e9927cCf430B` |
| V2 Federal Minter | `0xc15c5F699Daf5e1135732139f05D2c05b3EF4354` |
| V3 Index Minter | `0x0c4F73328dFCECfbecf235C9F78A4494a7EC5ddC` |
| V4 Personal Minter | `0x394c3D5990cEfC7Be36B82FDB07a7251ACe61cc7` |
| PulseX V1 Factory | `0x1715a3E4A142d8b698131108995174F37aEBA10D` |
| PulseX V2 Factory | `0x29eA7545DEf87022BAdc76323F373EA1e707C523` |
| PulseX V1 Router | `0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02` |
| PulseX V2 Router | `0x165C3410fC91EF562C50559f7d2289fEbed552d9` |
| SEI | `0x3dC54d46e030C42979f33C9992348a990acb6067` |
| CHAN | `0xe250bf9729076B14A8399794B61C72d0F4AeFcd8` |
| CHOA | `0x0f5a352fd4cA4850c2099C15B3600ff085B66197` |
| CHO | `0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB` |
| HECKE | `0x29A924D9B0233026B9844f2aFeB202F1791D7593` |
| WITHOUT (ban) | `0x173216Ed67eBF3E6767D86e8b3Ff32e0d64437bF` |

See `atropa_addresses.json` and `contracts.json` in project files for complete address lists.

---

## AFFECTION Deep Dive — Minting, Routes & Multi-Mint Contracts

**Source**: [affection.gitbook.io/docs](https://affection.gitbook.io/docs) (Helios / as-helios)
**Bot framework**: [gitea.bigpp.dev/as-helios/affection-bots](https://gitea.bigpp.dev/as-helios/affection-bots) (`core.py`)

### AFFECTION Contract Functions

AFFECTION (`0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D`) has multiple buy-in paths via dedicated contract functions. Each accepts a specific payment token at a fixed rate:

| Function | Payment Token | Cost per AFFECTION | Notes |
|----------|--------------|-------------------|-------|
| `BuyWithDAI(amount)` | pDAI | 1 pDAI | Direct 1:1 |
| `BuyWithUSDC(amount)` | pUSDC | 1 pUSDC | Direct 1:1 |
| `BuyWithMATH(amount)` | MATH v1.1 | 1 MATH | Direct 1:1 |
| `BuyWithG5(amount)` | GIMME FIVE | 0.2 G5 | 5 AFF per G5 |
| `BuyWithPI(amount)` | pINDEPENDENCE | 0.00333 PI | ~300 AFF per PI |
| `BuyWithFa(amount)` | Fa (libConjecture) | 4 Fa | |
| `BuyWithFaung(amount)` | Faung (libDynamic) | 2 Faung | |
| `Generate()` | (none — RNG) | gas only | Mints 3 AFF per call |

`Generate()` calls `_mintToCap()` 3 times — but **mints AFF to the AFFECTION contract's own `balanceOf(address(this))`**, NOT to the caller. To extract AFF, you must use `BuyWith*()` or `Purchase()` which transfer from the contract's self-balance to `msg.sender`. See "AFFECTION Verified Mechanics" below for full details.

### Arb Routes (Helios documented)

The arb exploits the price difference between contract fixed rates and DEX market prices. Profit range: 5% to 250% per trade.

**Route 1: pDAI → pINDEPENDENCE → DEX**
- Contract: `BuyWithDAI()` on pINDEPENDENCE costs 300 pDAI per PI
- If DEX price of PI > 300 pDAI equivalent → profit
- Multi-mint via `0xcCDaCEF154704c604365dB9E3b1DF356B9c4B6E2` (Multi PI): `multiBuyWithDAI(iterations)` loops up to 1000-2000x per TX

**Route 2: pDAI → GIMME FIVE → DEX**
- Similar pattern with G5 token

**Route 3: pDAI/pUSDC → MATH 1.1 → DEX**
- MATH accepts both pDAI and pUSDC

**Route 4: pDAI/pUSDC → [intermediate] → AFFECTION → DEX**
- Chain: pDAI → PI (300 pDAI/PI) → AFFECTION (0.00333 PI/AFF = ~1 pDAI/AFF) → swap AFF on PulseX
- Or: pDAI → G5 → AFFECTION → PulseX
- Or: pDAI/pUSDC → MATH → AFFECTION → PulseX

**Bug warning**: pUSDC and pUSDT are bugged for pINDEPENDENCE purchases — only pDAI works for that route.

### Multi-Mint Contracts (Gas Optimization)

Helios deployed batch-loop contracts that call mint/buy functions N times in a single TX. Bypasses MEV snipers and reduces per-unit gas cost to ~5-10 PLS.

| Contract | Address | Target Token |
|----------|---------|-------------|
| Multi PI | `0xcCDaCEF154704c604365dB9E3b1DF356B9c4B6E2` | pINDEPENDENCE |
| Multi G5 | `0xa4c61D20945c11855E7A390153fd29ceC9C7349b` | GIMME FIVE |
| Multi RNG | (see wiki) | RNG |
| Multi MATH 1.0 | `0x5bD78AdD4007C47ffEFc2c98a53188036199ac6f` | MATH v1.0 |
| Multi MATH 1.1 | `0x1322Dab9eE385Bb3D81f75EBb8356015B0872e53` | MATH v1.1 |
| **Multi AFFECTION** | **`0xCF138a83D739eE98D7A54159E94e5BFaa4B61988`** | AFFECTION |

### Multi AFFECTION Contract

Address: `0xCF138a83D739eE98D7A54159E94e5BFaa4B61988` (deployed 2025-05-06)

**Functions**:
- `multiGenerate(loops)` — calls `AFFECTION.Generate()` N times. **WARNING**: AFF stays in AFFECTION contract's self-balance. Does NOT deliver to caller. Only primes supply for `BuyWith*` calls.
- `multiBuyWith(address, loops)` — calls `multiGenerate(loops)` first, then buys AFF using payment token. **This is the function that actually delivers AFF to `msg.sender`**.

**perLoop costs** (hardcoded in constructor):
- G5: 0.6 per loop (0.2 per AFF)
- PI: 0.01 per loop (0.00333 per AFF)
- MATH: 3 per loop (1 per AFF)
- Fa: 12 per loop (4 per AFF)
- Faung: 6 per loop (2 per AFF)

**Usage pattern**:
1. Approve payment token to Multi AFFECTION contract (`type(uint256).max`)
2. Call `multiBuyWith(paymentTokenAddress, N)` where N = number of loops
3. Receive N × 3 AFFECTION back to caller (msg.sender)

**Constructor auto-approves** all payment tokens to AFFECTION contract with `type(uint256).max`. No per-call approval chain needed inside the contract.

### Integration with TGSv8

**Path A: Call BuyWith* directly from EOA**
Joey's wallet calls `AFFECTION.BuyWithPI(amount)` / `BuyWithG5(amount)` directly. AFF goes to `msg.sender` = Joey. Simplest path but requires acquiring payment tokens first via DEX.

**Path B: Use Helios Multi AFFECTION**
Call `multiBuyWith(paymentToken, N)` which batches Generate+Buy in one TX. More gas efficient for large batches. Requires payment token approval to Multi AFFECTION contract.

**Path C: Deploy custom contract (Grav's approach)**
Deploy a contract that:
1. Accepts payment tokens from caller
2. Calls `AFFECTION.BuyWithPI()` / `BuyWithG5()` in a loop
3. Receives AFF (as `msg.sender`)
4. Forwards AFF to `tx.origin` or specified recipient
See Grav's `0x32d390...` contract as reference implementation (4,579 bytes).

**Path D: Native TGSv9 integration**
Add a `batchBuyAffection(paymentToken, amount)` function that wraps BuyWith* calls with working balance management. Generate() alone is useless without the Buy step.

### AFFECTION Token Addresses (Complete)

| Token | Symbol | Address | Still Mintable |
|-------|--------|---------|---------------|
| pINDEPENDENCE | ⓟ | `0xA2262D7728C689526693aE893D0fD8a352C7073C` | Yes |
| GIMME FIVE | ⑤ | `0x2fc636E7fDF9f3E8d61033103052079781a6e7D2` | Yes |
| RNG | RNG | `0xa96BcbeD7F01de6CEEd14fC86d90F21a36dE2143` | Yes |
| libAtropaMath v1.0 | MATH | `0x5EF3011243B03f817223A19f277638397048A0DC` | Yes |
| libAtropaMath v1.1 | MATH | `0xB680F0cc810317933F234f67EB6A9E923407f05D` | Yes |
| libConjecture v1.0 | Fa | `0x232a27AB6941281b3f474Fe5fF7Cc89816fB675A` | Yes |
| libDynamic v1.0 | Faung | `0x73A19FaFb359faf519C9707b781dfdB88407d10d` | Yes |
| AFFECTION | Ⓐ | `0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D` | Yes |
| BLÄTTER | ออกจาก🄮 | `0xCe1d47CE3A91E054C111d9cC3B4bae50843200da` | No |
| Tetratricopeptides | 正 | `0x5F16F6c242e038437a7ba3C903DFeDB747Db4A5c` | Yes |
| pDAI | DAI | `0x6B175474E89094C44Da98b954EedeAC495271d0F` | — |
| pUSDC | USDC | `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` | — |

**Full spreadsheet**: [Google Sheets](https://docs.google.com/spreadsheets/d/18bPzn_T0EMv1reTz5ct6OZIomLu7fEOmAncSsSsyRlk/edit?gid=0#gid=0)

### Helios Bot Framework Reference

Source: `gitea.bigpp.dev/as-helios/affection-bots/src/branch/main/core.py`

Key functions for our bot integration:
- `mint_tokens(account, token_address, amount)` — loads RNG function list from `rng.json`, picks random mint function, loops
- `convert_tokens(account, token0, token1, amount)` — loads routes from `routes.json`, approves, calls BuyWith* function
- `convert_tokens_multi(account, multi_addr, token0, token1, iterations)` — uses multi-mint contracts for batch operations
- `sample_exchange_rate(router, token, quote)` — checks DEX price for arb profitability
- Gas monitoring: `get_beacon_gas_prices('rapid', cache_seconds)` with configurable ceiling

Data files: `rng.json` (mint functions per token), `routes.json` (conversion routes + costs + multi-mint configs)

---

## PLS Generation — Active Strategies

### Strategy A: DSS (Engine 2) — HIGHEST CONFIDENCE
`chatAndClaim` / `chatAndClaimWithMultiplier(17)` → 18 GIBS per call → swap to PLS via GIBS/WPLS pair.

- GIBS price: ~223 PLS (as of block 26,002,400)
- Break-even: ~21.5 PLS/GIBS
- **Currently 10x above break-even**
- Each cycle: ~4,014 PLS gross before gas
- Status: **UNLOCKED** — pair exists, price is right, ready for first income TX

### Strategy B: Treasury Sniping (Engine 6)
Scan treasury tokens for claimable backing. If child tokens cheaper to acquire than parent tokens received, execute.

**Recon results** (2026-03-12): E6 yields ~1-10K PLS after price impact. Not the primary driver.

### Strategy C: Spine Running (Engine 7)
V2 Federal mint-claim infinite loop on Debenture=True tokens.

**Current status**: Only OZZY has Debenture=true. OZZY's PLS/token is near-zero (1.54e-11). V2 Federal children are NOT profitable — need OZZY spine unlocked via E8 (Web Weaver) to create a viable path.

### Strategy D: V3 Family Exploitation (Future — E8 Required)
High-value V3 targets exist (MXDAI: 118 PLS/tok, 29M liq; S&㉿500: 44K PLS, 6M liq) but V3 Claim is family-isolated. Need to deploy sibling tokens as custom ammo. Requires MV tokens + parent token acquisition.

### Strategy E: Purchase→DEX Arbitrage (Engine 1)
AFFECTION routes across 272 QING venues. Currently net-negative per recon.

### Strategy F: AFFECTION BuyWith Routes — **CURRENTLY UNPROFITABLE** (Engine 4)

**STATUS**: DISABLED as of block 26,007,782. The `multiGenerate()` approach was based on a false assumption. See Session 11 for full analysis.

**What we learned (mainnet TX `0x9867...`, block 26,007,782)**:
- `multiGenerate(100)` succeeded — 300 AFF minted to AFFECTION contract's self-balance
- AFF did NOT arrive in Joey's wallet — `_mintToCap()` mints to `address(this)` always
- Cost: ~3,357 PLS gas for a public-good supply increase (no private benefit)
- **`multiGenerate()` alone is useless** — it primes supply but doesn't extract

**The correct mechanism** (verified via Grav's bot pipeline):
1. Acquire payment tokens (PI, G5, MATH via DEX)
2. Call `BuyWithPI()` / `BuyWithG5()` on AFFECTION — this transfers AFF to `msg.sender`
3. Sell AFF on DEX for PLS

**Current break-even analysis** (block 26,007,910):

| Route | Cost/AFF (pDAI equiv) | AFF DEX Price (pDAI equiv) | Status |
|-------|----------------------|---------------------------|--------|
| pDAI → PI → BuyWithPI | 1.0000 pDAI | 0.3624 pDAI | -64% loss |
| pDAI → G5 → BuyWithG5 | 0.8509 pDAI | 0.3624 pDAI | -57% loss |
| PLS → pDAI → PI → AFF → PLS | ~41,700 PLS cost | ~15,112 PLS out | -64% loss |

**Profitability trigger**: AFF must trade above ~118 PLS (G5 route) or ~139 PLS (PI route) for BuyWith paths to become profitable. Currently at ~50 PLS.

**WM comparison**: Also unprofitable — 23.2 PLS/WM mint cost vs 17.0 PLS DEX price.

**DEX liquidity** (unchanged): V2 pool has 5.7M AFF / 292M WPLS. Selling 300 AFF = 0.005% impact.

**AFF supply**: 177.9M of ~1B minted. AFFECTION self-balance: 3,233 AFF (includes our 300 from the failed multiGenerate).

---

## AFFECTION Verified Mechanics (Session 11 — On-Chain Verified)

### _mintToCap() — The Core Mint Pattern

From `solidity/dysnomia/01_dysnomia.sol`:
```solidity
function _mintToCap() internal {
    if(totalSupply() < (maxSupply * 10 ** decimals()))
        _mint(address(this), 1 * 10 ** decimals());  // ← MINTS TO SELF
}
```
**ALL DYSNOMIA tokens mint to `address(this)`.** This is not a bug — it's the design. Tokens accumulate in the contract's own balance and are extracted via `Purchase()` or `BuyWith*()`.

### Purchase() — The Extraction Function

```solidity
function Purchase(address _t, uint256 _a) public {
    if(_marketRates[_t] == 0) revert MarketRateNotFound(_t);
    DYSNOMIA BuyToken = DYSNOMIA(_t);
    uint256 cost = (_a * _marketRates[_t]) / (10 ** decimals());
    bool success1 = BuyToken.transferFrom(msg.sender, address(this), cost);
    require(success1, string.concat(unicode"Need Approved ", BuyToken.name()));
    DYSNOMIA(address(this)).transfer(msg.sender, _a);  // ← TRANSFER TO CALLER
}
```
Caller pays `_marketRates[_t]` units of token `_t`, receives `_a` units of this token from the contract's self-balance.

### Generate() — Verified On-Chain Source

From AFFECTION contract (`0x24F0...`, verified via Blockscout):
```solidity
function Generate() public returns(uint64) {
    Amplify(Mu.Cone, Mu.Upsilon);   // triggers _mintToCap() internally
    Sustain(Mu.Cone, Mu.Ohm);       // triggers _mintToCap() internally
    React(Mu.Cone, Mu.Pi, Mu.Cone.Dynamo);  // triggers _mintToCap() internally
    React(Mu.Rod, Mu.Pi, Mu.Rod.Dynamo);
    Mu.Omega = Mu.Omega ^ Mu.Rod.Kappa;
    Mu.Upsilon = Mu.Upsilon ^ Mu.Ohm ^ Mu.Pi;
    _mintToCap();
    return Mu.Upsilon;
}
```
Confirmed via TX receipt: **3 mints per call** (300 mints / 100 loops in `multiGenerate(100)` TX `0x9867...`). The 3 mints come from Amplify + Sustain + the explicit `_mintToCap()` at the end. All mint to `address(this)`.

**AFFECTION supply cap**: `1,111,111,111` tokens (hardcoded in `_mintToCap()` override: `totalSupply() <= 1111111111 * 10**decimals()`).

### Generate() → _mintToCap() → Self-Balance Flow

```
Generate()
  ├── _mintToCap() × 3  →  +3 AFF to balanceOf(AFFECTION_contract)
  └── NO transfer to caller

BuyWithPI(amount)
  ├── transferFrom(caller, AFFECTION, cost_in_PI)  ← caller pays PI
  ├── _mintToCap() × 3  →  +3 AFF to self-balance (supply priming)
  └── transfer(caller, amount)  ← AFF delivered to msg.sender

multiGenerate(N)
  ├── Generate() × N  →  +3N AFF to self-balance
  └── NO transfer (just primes supply)

multiBuyWith(paymentToken, N)
  ├── multiGenerate(N)  →  +3N AFF to self-balance
  ├── BuyWith*(3N)  →  pulls payment, transfers 3N AFF to msg.sender
  └── AFF DELIVERED to msg.sender ✓
```

### Function Selectors (Verified)

| Function | Selector | Delivers AFF? |
|----------|----------|---------------|
| `Generate()` | `0xd805b650` | NO — mints to contract |
| `Purchase(address,uint256)` | `0x2499a533` | YES → msg.sender |
| `BuyWithDAI(uint256)` | `0x377de122` | YES → msg.sender |
| `BuyWithPI(uint256)` | `0xca9cf41c` | YES → msg.sender |
| `BuyWithG5(uint256)` | `0xb61a722b` | YES → msg.sender |
| `BuyWithMATH(uint256)` | `0x512ab7de` | YES → msg.sender |
| `BuyWithFa(uint256)` | `0xf8784afe` | YES → msg.sender |
| `BuyWithFaung(uint256)` | `0x5118149a` | YES → msg.sender |
| `multiGenerate(uint256)` | `0xd1f05872` | NO — just primes supply |
| `multiBuyWith(address,uint256)` | `0xcc93bb90` | YES → msg.sender |

### Grav's AFFECTION Bot Pipeline (Reverse-Engineered)

**Operational window**: Blocks ~21,009,000 – 21,133,000 (~5M blocks ago)
**Total volume**: 3,248,259 AFF across 5,745 batches (~565 AFF/batch)
**pDAI spent**: 405,684 pDAI → effective cost: ~0.125 pDAI/AFF

**Bot addresses**:
| Role | Address | Nonces | PLS Balance |
|------|---------|--------|-------------|
| Minter | `0x217a76D9BEf7CeC27eFB5039099221241ca26F93` | 27,657 | 108,456 PLS |
| Buyer (savings) | `0x1B79F904087DaaF6C67d7AD2cfA1D7c727De885B` | 13,702 | 57,583 PLS |
| Seller | `0xa767a0D5E04eD4c90Ad68F316A9E55090aa28c51` | 27,393 | 20,259 PLS |

**Pipeline flow**:
```
pDAI/WPLS V2 Pair (0xae84...)           ← PLS → pDAI swap
  ↓ 405,684 pDAI
Minter Bot (0x217a...)
  ├→ Multi PI contract (0x3026...)       ← pDAI → BuyWithDAI → PI (114 batches, 1,213 PI)
  ├→ Multi G5 contract (0xa4c6...)       ← pDAI → G5 (83 batches, 7,288 G5)
  ↓ PI + G5 tokens
Custom BuyWith Contract (0x32d3...)      ← Grav's deploy, 4,579 bytes, nonce=1
  ├→ AFFECTION.BuyWithPI() / BuyWithG5() ← payment token → AFFECTION contract
  ├→ AFF from AFFECTION self-balance → contract (msg.sender)
  ↓ AFF forwarded to Minter (tx.origin)
Minter → Seller (0xa767...)
  ↓ 10,119 swaps on AFF/WPLS V2 Pair (0x1551...)
  ↓ AFF → WPLS → PLS profit

Savings path: Seller → Buyer (2,056 transfers, 80,782 AFF held back)
```

**Key contracts in Grav's pipeline**:
| Contract | Address | Purpose |
|----------|---------|---------|
| Custom BuyWith wrapper | `0x32d390e9e1b1dc7af2349312ad55be81dfc6398c` | Calls BuyWithPI/G5, forwards AFF to tx.origin |
| Multi PI (not Helios's) | `0x3026512fd7116e0a6b6db942f263cc9eef063143` | pDAI → PI batch mint |
| Multi G5 (Helios's) | `0xa4c61D20945c11855E7A390153fd29ceC9C7349b` | pDAI → G5 batch mint |
| AFF/WPLS V2 sell pair | `0x155172653e94a7e5f0e04126803dcb6896796fbb` | AFF sell target (factory: PulseX V2) |
| pDAI/WPLS V2 pair | `0xae8429918fdbf9a5867e3243697637dc56aa76a1` | PLS → pDAI acquisition |

**Why it was profitable then but not now**: Grav ran this when AFF DEX price was higher relative to pDAI cost. The BuyWith fixed rates (1 pDAI/AFF via PI route) made arbitrage profitable when AFF traded above ~1 pDAI on DEX. Currently AFF ≈ 0.36 pDAI equivalent — deeply underwater.

### Payment Token Intermediate Rates (from Helios wiki)

Each payment token has its own BuyWith functions for acquiring it. These are the **fixed contract rates** (not DEX):

| Token | BuyWithDAI Rate | BuyWithUSDC | BuyWithUSDT | Notes |
|-------|----------------|-------------|-------------|-------|
| pINDEPENDENCE | 300 pDAI/PI | 300 pUSDC/PI | 300 pUSDT/PI | **pUSDC/pUSDT BUGGED** — only pDAI works |
| GIMME FIVE | 5 pDAI/G5 | 5 pUSDC/G5 | 5 pUSDT/G5 | **pUSDC/pUSDT BUGGED** |
| MATH v1.1 | 1 pDAI/MATH | 1 pUSDC/MATH | 1 pUSDT/MATH | pUSDT bugged, pUSDC works |
| RNG | 1 pDAI/RNG | 1 pUSDC/RNG | 1 pUSDT/RNG | Also: BuyWithG5(4:1), BuyWithPI(212:1) |

**Full cost chain to AFFECTION** (fixed contract rates):
- PI route: 300 pDAI → 1 PI → 300 AFF → **1.00 pDAI/AFF**
- G5 route: 5 pDAI → 1 G5 → 5 AFF → **1.00 pDAI/AFF**
- MATH route: 1 pDAI → 1 MATH → 1 AFF → **1.00 pDAI/AFF**

All routes converge to ~1 pDAI/AFF through contract rates. Profit only exists when AFF DEX price > 1 pDAI equivalent (~139 PLS at current pDAI/PLS rate).

---

## Treasury Recon Key Findings (2026-03-12)

### V2 Federal Token Scan
From `v2_federal_tokens.json` — 14 tokens scanned:
- **13 of 14 have Debenture=false** (published, Claim locked)
- **Only OZZY has Debenture=true** — but PLS/token is ~1.54e-11 (near-zero value)
- FDIC selfBalance: 14.3T tokens, but at 1.25e-8 PLS/token = negligible
- BAR selfBalance: 11.2Q tokens, at 1.03e-10 PLS/token = negligible
- SCOIETY selfBalance: 148.8T tokens, at 1.18e-11 PLS/token = negligible

**Conclusion**: V2 Federal children are NOT profitable for E7 spine running.

### Real High-Value Targets (V3 Index Tokens)
The big money is in non-Federal Debenture=True tokens with high PLS/token:
- **MXDAI**: 118 PLS/token, 29M PLS liquidity (parent=pDAI)
- **S&㉿500**: 44K PLS/token, 6M PLS liquidity (parent=N㉾SD㉾Q)

But V3 Claim() family isolation blocks direct exploitation — need same-creator, same-parent sibling as ammo.

### Federal Claim() Two Paths
1. **V2 tokens**: Need Debenture=true on spend token
2. **V1 tokens**: Bypass Debenture check entirely — Claim always open

### Strategic Implications
- E2 (DSS) is the highest-confidence near-term income engine
- E7 as originally designed does not work on V3 targets
- E8 (Web Weaver) is the unlock: deploy V3 sibling tokens as custom ammo for high-value families
- OZZY ammo is near-free but target tokens have near-zero value

---

## Current State Snapshot (Block 26,002,400 — 2026-03-12)

### Wallet Balances
```
PLS:           1,991,521
GIBS:          169
AFFECTION:     97.18
WM:            263.15
ATROPA:        166.78
VOID:          51.22
TGSv8 holds:   7 WM
Nonce:         113
```

### Market Prices
```
GIBS price:    223.18 PLS ($1.58)
PLS/USD:       $0.00708
```

### Engine Readiness
```
E1 (RAZOR arb):           Ready — net-negative per recon, low priority
E2 (CEREAL DSS):          UNLOCKED — 10x above break-even, awaiting first cycle
E3 (MERIDIAN Beat):       Running — Dione=41
E4 (Token Factory):       AFF DISABLED — multiGenerate mints to contract, BuyWith routes unprofitable
E5 (LAU ABUPRU):          Gated — 150K PLS floor
E6 (DaVINCI Sniper):      Needs recon targets — ~1-10K PLS yield
E7 (BACKBONE Spine):      Needs OZZY spine via E8
```

### Last 2 TGSv8 Transactions
- `swapNativeForTokens(500 PLS)` — test swap
- `withdraw` — test withdrawal

---

## Session Logs

### Sessions 1–4 (2026-02-27 – 2026-02-28)
LAU creation, Beat analysis, SHIO acquisition, wallet encryption. See earlier entries for detail.

### Session 5 (2026-03-01) — Joystick Bot + TGSv5

**Branch**: `claude/optimize-pls-generation-OlVDG`

- Built Joystick bot (23 files, 4-engine modular architecture)
- Deployed TGSv5 at `0xeeB330d3...` (block 25,911,970, 816 PLS gas)
- Engine 3 (WM batch mint) activated

### Session 6 (2026-03-02) — Engine 6 LAU-ABUPRU

**Branch**: `claude/joystick-lau-engine-Zq7i5`

- Engine 6 LAU-ABUPRU + EmitSniper (merged via PR #3)
- PLS gate at 150K threshold

### Session 7 (2026-03-04) — Branch Consolidation + Workflow

**Branch**: `claude/Joystick-Engines-Lj9Kp` (canonical)

- Audited all session branches
- Established merge workflow (`merge-session.sh`)
- Confirmed TGSv8 deployment
- Set GitHub default branch

### Session 8 (2026-03-04 – 2026-03-05) — TGSv7 → TGSv8 Deploy

**Diary entries**: 06, 07

**Key events**:
- TGSv7 deployed (block 25,938,174, 5,972 PLS) — discovered V4 mint 2x transferFrom bug → fixed with `type(uint256).max` approval
- **TGSv8 deployed** (block 25,943,194) — added native `mintWM()`, removed TGSv5 dependency, added `getReservesBoth()` dual-DEX oracle
- **JV8A deployed** (block 25,943,266) — first V4 personal treasury token via TGSv8.createV4()
- 7 MV tokens seeded into TGSv8 working balance
- Deploy toolchain lessons: PulseChain gas = Beats not Gwei, `--gas-beats` manual override, receipt timeout 120s

**TGSv8 key additions over v7**:
- `mintWM(count)` — batch WM minting, no external dependency
- `getReservesBoth()` — V1+V2 reserves in one call
- Native PLS in/out: `swapNativeForTokens()`, `swapTokensForNative()`, `wrapPLS()`, `unwrapWPLS()`
- Step.dex field in executeRoute — per-step DEX selection

**Balance**: ~41,248 PLS (depleted from deploys)

### Session 9 (2026-03-09) — GIBS LP Deployment + E2 Unlock

**Diary entry**: 08

**Key events**:
- **PLS stimulus arrived**: ~1.95M PLS, balance jumped to 1,992,199 PLS
- **10 GIBS LP pairs deployed** across PulseX V1 and V2:
  - 3,226 GIBS deployed to LP (170 GIBS held in savings)
  - Partner tokens acquired with <1% price impact per trade
  - ATROPA routed through pDAI intermediate for cleanest execution
- **Engine 2 UNLOCKED**: GIBS/WPLS pair at 219 PLS/GIBS (10x above 21.5 PLS break-even)
- AMM bots immediately began arbing between pairs — 24h volume nonzero
- DFM/PARADE/TLRz pairs arbed to near-empty GIBS (bots bought cheap GIBS and sold at 400x markup)
- Joey holds LP positions on both sides of arb trades — collecting fees both ways

**86 transactions executed** (nonce 25 → 111)

**Balance**: 1,992,199 PLS, 169 GIBS, 88 AFFECTION, 263 WM

### Session 10 (2026-03-12) — Treasury Recon Deep Dive

**Focus**: Scan GIBS LP status, wallet state, treasury recon verification

**Key events**:
- Scanned all 10 GIBS LP pairs — all live, AMM activity ongoing
- **Built claim_verifier.py** — eth_call simulation of Claim() on top 10 recon targets
- **Critical discovery**: All high-value targets are V3 Index Minter tokens (not V2 Federal)
- V3 Claim() has family isolation: same-creator + same-parent + registered requirement
- MXDAI (118 PLS/tok) — only child in family, no sibling ammo exists
- S&㉿500 family — 7 siblings but all at 0 PLS/token with zero DEX liquidity
- V2 Federal children confirmed near-zero PLS/token across the board
- E7 Spine Runner as designed **does not work** for V3 targets
- E8 Web Weaver identified as the critical unlock for high-value exploitation
- E2 (DSS) confirmed as highest-confidence income engine

**Balance**: 1,991,521 PLS, 169 GIBS, 97.18 AFFECTION, 263.15 WM (nonce 113)

### Session 11 (2026-03-12) — AFFECTION Mainnet Test + Grav Pipeline Recon

**Branch**: `claude/add-affection-minting-KhBTl`

**Focus**: Live mainnet test of AFFECTION Generate(), reverse-engineer Grav's profitable bot pipeline

**Key events**:
- **Built E4 TokenFactory AFF Generate mode** — added `multiGenerate()` integration, route auditor, batch gas estimation
- **RPCPool bug discovered**: Multi-provider `send_raw()` causes "replacement transaction underpriced" when first provider accepts TX but second rejects as duplicate. Fixed by using single-RPC direct path for critical TXs.
- **MAINNET TX `0x9867...` (block 26,007,782)**: `multiGenerate(100)` succeeded (4,005,067 gas) — but 300 AFF minted to AFFECTION contract's self-balance, NOT to Joey. **Critical finding**: `_mintToCap()` always mints to `address(this)`.
- **AFF Generate mode DISABLED** — `AFF_GENERATE_ENABLED = False` in token_factory.py
- **Reverse-engineered Grav's 3-bot AFFECTION pipeline** via on-chain Transfer event analysis:
  - Minter bot (`0x217a...`, 27,657 TXs) → acquires PI/G5 via pDAI
  - Custom contract (`0x32d3...`) → calls `BuyWithPI()`/`BuyWithG5()`, forwards AFF to tx.origin
  - Seller bot (`0xa767...`) → swaps AFF on PulseX V2 pair
  - Total: 3,248,259 AFF farmed, 405,684 pDAI spent across 5,745 batches
  - Pipeline was profitable when AFF > 1 pDAI on DEX; currently at ~0.36 pDAI (unprofitable)
- **Verified all BuyWith function selectors** and confirmed `msg.sender` delivery pattern
- **Current route profitability**: All BuyWith routes net-negative. PI route: -64%. G5 route: -57%.

**Losses this session**: ~3,357 PLS gas (multiGenerate TX that increased AFFECTION public supply)

**Balance**: ~1,988,164 PLS, 169 GIBS, 97.18 AFF, 263.15 WM (nonce 114)

---

## Key Bugs & Lessons Learned

- **V4 mint 2x transferFrom**: V4 minter pulls 2x the requested amount via transferFrom. Fix: approve `type(uint256).max` (TGSv8 fix)
- **`execute 0 X func arg` bug**: C# command overwrites Alias with account number string. Use `execute X func arg` (no leading 0)
- **C# `SendTransactionAsync` hang**: Nethereum hangs on PulseChain. All TX moved to Python web3.py
- **MultiOwnable ownership trap**: `owner()` returns `address(this)` not EOA. MAP.New() adds LAU CONTRACT as QING owner, not Joey's wallet
- **V1 vs V2 AFFECTION**: DYSNOMIA v1 constructor calls `AddMarketRate(AFFECTION, ...)` internally. V2/QING does NOT — requires manual call by owner
- **PulseChain gas units**: `eth_gasPrice` returns Impulses (wei-equiv). Divide by 10^9 for Beats. Display confusion caused stuck TX on publicnode
- **RPC strategy**: `rpc-pulsechain.g4mm4.io` or `rpc.pulsechain.com` for reads; `rpc.pulsechain.com` for TX submit. `pulsechainstats.com` is read-only (no TX)
- **`_mintToCap()` mints to self**: ALL DYSNOMIA tokens mint to `address(this)`, not to `msg.sender` or `tx.origin`. Must use `Purchase()` or `BuyWith*()` to extract. `Generate()` and `multiGenerate()` alone do NOT deliver tokens to the caller.
- **RPCPool "replacement TX underpriced"**: When RPCPool tries multiple Tier 1 providers for `send_raw()`, the second provider may reject the same TX as "replacement transaction underpriced" if the first already accepted it. For critical single TXs, use a single RPC endpoint via `Web3.HTTPProvider()` directly to avoid this race.
- **multiGenerate() is a public good**: Calling `multiGenerate(N)` spends your gas to increase AFFECTION's self-balance supply — anyone can then buy it via `BuyWith*`. This is a donation, not a profit operation.

---

## QING Ownership Puzzle — UNRESOLVED

**Problem**: `GIBS_QING.AddMarketRate` is `public onlyOwners`. Joey's EOA is NOT an owner.

GIBS_QING owners: GIBS_LAU contract + CHO contract. MAP renounced itself.

**Unlock key**: `CHO.AddContractOwner(GIBS_QING, Joey)` — requires CHO deployer or GIBS_QING contract to call. Neither Noumenon nor Joey can call it.

**Workaround applied**: GIBS_LAU uses DYSNOMIA v1 (AFFECTION rate set at birth). `Purchase()` on GIBS_LAU works at 1:1.

---

## BEAT Analysis

**Function**: `META.Beat(uint256 QingWaat)` → `(Dione, Charge, Deimos, Yeo)`

**Call chain**: 10+ contracts deep. Requires SHIO token balances (Fornax, Fomalhaute, CHO) at GIBS_LAU and GIBS_QING.

**Current status**: Running. Dione=41. WORLD not yet deployed on-chain.

**SHIO balances confirmed** (block 25,903,711):
| Token | @ GIBS_LAU | @ GIBS_QING |
|-------|-----------|------------|
| Fornax | 0.150000 | 0.150000 |
| Fomalhaute | 0.001387 | — |
| CHO | 0.002921 | 0.002921 |

**Root cause of prior Beat revert**: `RING.Moments[Soul]` = 0 → Iota=0 → division by zero. Fix: run `CHEON.Su()` first to initialize YUE bar state.

---

## Key Implementation Files

### Solidity
- `solidity/dysnomia/01_dysnomia.sol` — Base token, AFFECTION market rate, Purchase()
- `solidity/dysnomia/10_void.sol` — VOID game controller
- `solidity/dysnomia/11_lau.sol` — LAU player token
- `solidity/dysnomia/domain/tang/03_meta.sol` — META.Beat()
- `solidity/dysnomia/domain/tang/02_cheon.sol` — CHEON.Su()
- `solidity/dysnomia/etc/DysnomiaSelfSnipev4.sol` — DSS (pragma ^0.8.21, no OZ imports)
- `contracts/TGSv5.sol` — WM batch minter (legacy)
- TGSv8 — Full source in project files

### Python (Joystick bot)
- `scripts/Joystick/bot.py` — Priority scheduler
- `scripts/Joystick/core/` — config, chain, wallet, executor, gas_guard, simulator
- `scripts/Joystick/oracle/` — price, scanner, profitability
- `scripts/Joystick/engines/` — arb.py, dss.py, beat.py, token_factory.py, lau.py, treasury_sniper.py, spine_runner.py
- `scripts/Joystick/tools/claim_verifier.py` — eth_call Claim() simulation on recon targets

### Python (standalone scripts)
- `scripts/tx_full_beat_flow.py` — Full Beat orchestration (SHIO → Su() → Beat)
- `scripts/tx_cheon_su.py` — CHEON.Su() YUE bar primer
- `scripts/scan_lau_arb.py` — Scan 272 QINGs for Purchase→DEX arb
- `scripts/tx_lau_arb.py` — Execute arb loop
- `agent/wm_minter.py` — TGSv5 WM batch-mint agent

### Python (research / analysis)
- `scripts/test_aff_mint.py` — AFFECTION multiGenerate mainnet test harness (full 7-step)
- `scripts/test_aff_direct.py` — Direct single-RPC AFF mint test (bypasses RPCPool race)
- `scripts/analyze_aff_bots.py` — Grav's bot pipeline Transfer event scanner
- `scripts/analyze_aff_bots_v2.py` — Extended pipeline analysis with payment token tracing

### Data files
- `scripts/Joystick/data/recon_results.json` — Full treasury recon (39K lines, 1.26 MB)
- `scripts/Joystick/data/claim_verification.json` — Claim() eth_call simulation results
- `scripts/Joystick/data/v2_federal_tokens.json` — V2 Federal token scan

---

## On-Chain Intelligence Notes

- **Noumenon** (`0xEbE9B8673d...`) — 2,473+ txs, active gifter, gifted Joey 100 AFFECTION
- **MAP** has 272+ QINGs — venue ecosystem is active
- **Active bot**: `0xb1c9b8d6...` → `0xc078C8DaE2...` running chatAndClaim-style loop
- **Enteh** — 25-26 successful Beat calls, skips CHEON.Su() entirely
- **RatKing** (`0x530c8cE7...`) — Fornax whale (25K)
- **GIBS LP arb bots** found the 9,852 PLS/GIBS implied price on thin pools and immediately arbed back toward parity — Joey earns fees on both sides
- **Grav's AFFECTION pipeline** — 3-bot system: Minter (`0x217a76D9...`, 27,657 nonce), Buyer/savings (`0x1B79F904...`, 13,702 nonce), Seller (`0xa767a0D5...`, 27,393 nonce). Farmed 3.25M AFF via pDAI→PI/G5→BuyWith→DEX sell. Custom intermediary contract at `0x32d390e9...`. Active around blocks 21M-21.1M, currently idle.
- **AFF/WPLS V2 sell pair**: `0x155172653e94a7e5f0e04126803dcb6896796fbb` (PulseX V2 factory, token0=AFF, token1=WPLS)
- **pDAI/WPLS V2 pair**: `0xae8429918fdbf9a5867e3243697637dc56aa76a1` (PulseX V2)

---

## Session Log — Joey Is Live

| Event | TX / Address | Block |
|-------|-------------|-------|
| GIBS LAU deployed | → `0x66a08aa...` | 26,215,664 |
| Username "Joey" set | `0x1d46e25...` | 25,886,977 |
| DysnomiaSelfSnipev4 deployed | → `0x91Df693...` | 25,887,000 |
| SEI.Start() — YUE wallet | → `0x8e666227...` | 25,893,644 |
| MAP.New(GIBS) — QING venue | → `0x1B8774C0...` | 25,893,651 |
| DSS.setChatMultiplier(17) | | 25,893,803 |
| Handle \|>JOYSTICK<\| acquired | `0x2eb66e1b...` | 25,894,338 |
| GIBS_LAU.Purchase(AFFECTION, 2) | `0xd18db450...` | 25,894,498 |
| TGSv5 deployed | → `0xeeB330d3...` | 25,911,970 |
| TGSv7 deployed | → `0x82E8B7e2...` | 25,938,174 |
| **TGSv8 deployed** | → `0xAD352a27...` | 25,943,194 |
| **JV8A created via TGSv8** | → `0x364793Ea...` | 25,943,266 |
| **10 GIBS LP pairs deployed** | (86 txs, nonce 25→111) | ~25,984,143 |
| **TGSv8 test: swapNativeForTokens** | | ~26,002,xxx |
| **TGSv8 test: withdraw** | | ~26,002,xxx |
| **multiGenerate(100) — AFF to contract** | `0x9867...` | 26,007,782 |

---

## What's Next

1. **Run E2 first DSS cycle** — `chatAndClaim` at 223 PLS/GIBS. Highest-confidence income engine. No blockers.
2. **Monitor AFF/pDAI price ratio** — BuyWith routes become profitable when AFF > ~118 PLS (currently ~50 PLS). E4 auto-monitors.
3. **E4 AFF BuyWith path** — when prices align: acquire cheapest payment token (MATH or G5) on DEX, call `BuyWithMATH()` / `BuyWithG5()` directly from EOA. No custom contract needed for basic flow.
4. **E3 dual-mode monitoring** — WM currently unprofitable (23 PLS cost vs 17 PLS value), scan for crossover
5. **Monitor GIBS LP pairs** — arb activity ongoing, fees accumulating
6. **E8 Web Weaver design** — deploy V3 sibling tokens as ammo for MXDAI/S&㉿500 families
7. **Helios AFFECTION wiki deep dive** — scrape affection.gitbook.io/docs for additional routes and mechanics not yet discovered

**Last Updated**: 2026-03-12 (block 26,007,782)
**Status**: OPERATIONAL. 10 GIBS LP pairs live. E2 unlocked at 10x break-even. E4 AFF Generate DISABLED (mints to contract, BuyWith routes unprofitable). Treasury recon + Grav pipeline recon complete.
