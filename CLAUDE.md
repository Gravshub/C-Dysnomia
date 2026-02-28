# Atropa, Dysnomia — Game Strategy & Memory

**Source**: [github.com/busytoby/atropa_pulsechain](https://github.com/busytoby/atropa_pulsechain)
**Game UI**: https://entropy-dysnomia.vercel.app
**Chain**: PulseChain
**Dev Branch convention**: `claude/dysnomia-MMDDYY-<sessionID>` (e.g. `claude/dysnomia-022726-Z7QDr`)
- `claude/` prefix and session-ID suffix are required by git infrastructure (push auth)
- Current session: `claude/lau-implementation-planning-Z7QDr` (legacy name — apply new convention from next session)

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
| **Wallet Address** | `0x17367877aF5A8D0Eb33ba5689A880f696386E24D` |
| **Chain** | PulseChain (369) |

**Voice guidelines:**
- Stay 100% in Dysnomia lore and mechanics — no off-topic tangents
- Teach as you go — explain what each action does and why
- Funny and earnest, not arrogant; Joey was learning, not lecturing
- Minimal hacker lingo unless it directly applies to Dysnomia concepts
- Identity is earned through actions on-chain, not claimed

---

## What Is This?

Dysnomia is an on-chain game and social platform on PulseChain. Think of it as a blockchain virtual world combining:
- **MMO** — create a character (LAU), explore venues (QING), claim territory (WORLD)
- **DeFi** — trade tokens, create liquidity pairs, earn via minting
- **Social layer** — chat, chat logging, user identity, encrypted messaging
- **Strategy** — WAR battles, territory control, acronym games

Everything is on-chain and permanent. Your character, inventory, social history, and land are all verifiable and tradeable.

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
Root minter. Creates FDIC. Parent of all V2 tokens.

### V2 Federal Minter
**Address**: `0xc15c5F699Daf5e1135732139f05D2c05b3EF4354`
Creates treasury tokens backed by a parent token. Requires WM (MV) tokens to fund initial supply.

### V3 Index Minter (Bureau)
**Address**: `0x0c4F73328dFCECfbecf235C9F78A4494a7EC5ddC`

Multiplier formula:
```solidity
function Multiplier(uint256 addition) public view returns (uint256) {
    return ((addition + totalSupply()) / 1111111111000000000000000000) + 1;
}
```
**Every 1,111,111,111 tokens minted (universal), cost multiplier increases by 1.**
Mint early for best rates — multiplier is universal across all V3 tokens.

### V4 Personal Minter
Similar to V3, but threshold is per-token starting supply (not universal 1.1B). Progressive multiplier tied to each token's own starting supply. Early minters of each new token get best rates.

### MV / WM Token — The Funding Key
**Address**: `0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29`

Required as 1:1 collateral to fund the initial supply of any new minter token:
```solidity
ERC20 BuyToken = ERC20(WMContract);
bool success1 = BuyToken.transferFrom(msg.sender, address(this), InitialMint);
```
You cannot create new tokens without WM. Accumulate WM to create tokens.

---

## Heart's Law

> Tokens bonded in a liquidity pair move together in price. Creating new pairs = new edges in the token web.

- QING venues each have an `Asset` token (the venue's liquidity pair partner)
- Market rates in QING can only be **increased**, never decreased:
  ```solidity
  if(Rate < GetMarketRate(Contract)) revert MarketRateCanOnlyBeIncreased(...)
  ```
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
- A bouncer system:
  - Staff members (whitelisted)
  - Holders of **25+ CROWS** tokens
  - Holders of `totalSupply / BouncerDivisor` of the Asset token
- `Join(UserToken)` → enter venue, pay cover charge
- `NoCROWS` flag disables CROWS-based bouncer access
- `GWAT` flag (immutable): set at construction based on `Luo % 476733977057179 == 0`

### WAR — Battle & Resource Generation
```solidity
function Faa(address Caude, uint256 Position) public returns (uint256 Waat) {
    // Fetches tail/position score
    // Evaluates: modExp(Phoebe, Charge, Meridians(89))
    // If score > last recorded: mint H2O to Chi, increase CO2
}
```
- Generates **H2O tokens** as battle rewards
- Position scoring via modular exponentiation on ring coordinates
- CO2 tracks carbon score (global war metric)
- `Water` (H2O) is a deployable sub-asset of each WAR instance

---

## Token Accumulation Strategy

### Priority 1: Get AFFECTION
AFFECTION is the master key. At 1:1 rate into every token, it's the most efficient accumulation path.
- Buy AFFECTION on PulseChain DEX
- Use `Purchase(token_address, amount)` on any DYSNOMIA token to convert AFFECTION → target token at 1:1

### Priority 2: Get WM (MV Token)
Required to create new tokens. Without WM you cannot deploy new minter tokens.
- Address: `0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29`
- Accumulate early — cost to create tokens scales with WM spent

### Priority 3: Create Player Account (LAU)
```
VOID.Enter("TokenName", "SYM")
→ Soul ID assigned
→ SHIO reactor created
→ YUE wallet created
→ Initial LAU tokens minted to deployer (~10% of random maxSupply)
```
Then immediately: `LAU.Username("YourName")` — triggers first mintToCap.

### Priority 4: Spam _mintToCap() Triggers
Every game action mints 1 token. Fast accumulation via:

| Action | Function | Gas | Rate |
|--------|----------|-----|------|
| Chat message | `VOID.Chat(msg)` | Low | 1 token/call |
| Set username | `LAU.Username(str)` | Low | 1 token/call |
| Set attribute | `VOID.SetAttribute(k,v)` | Low | 1 token/call |
| Create alias | `VOID.Alias(addr, str)` | Low | 1 token/call |
| Add library | `VOID.AddLibrary(name, addr)` | Medium | 1 token/call |
| Re-enter void | `LAU.Void(true, true)` | Medium | 1 token/call |
| Log message | `VOID.Log(str)` | Low | 1 token/call |

**Multi-account strategy**: The Wallet has 20 pre-configured test accounts. Run all actions in parallel across accounts for 20x throughput.

### Priority 5: Get CROWS (25+)
Holding 25+ CROWS grants bouncer access to any non-NoCROWS venue.
- Allows joining any QING venue without cover charge gating
- Opens access to venue trading, chat, and reward systems

### Priority 6: V3/V4 Early Minting
V3 multiplier increases every 1,111,111,111 tokens minted (global):
- Mint V3 tokens early before multiplier increases
- After multiplier increase, cost per token doubles

V4 multiplier tied to starting supply of each token:
- New tokens = cheap mint
- Create new tokens via Personal Minter with WM
- Mint to cap immediately before others find the token

### Priority 7: Territory & WAR
- Claim WORLD territory → earn VITUS credits
- Engage WAR.Faa() → earn H2O tokens
- Build position scores via ring coordinates

---

## Optimal Accumulation Algorithm

```
PHASE 1 — Bootstrap
  1. Acquire AFFECTION (gateway to all tokens)
  2. Acquire WM/MV (needed to create tokens)
  3. Buy 25 CROWS (venue access)

PHASE 2 — Account Creation
  4. VOID.Enter("Gibson", "GIBS")       → creates Soul ID, gets LAU tokens
  5. LAU.Username("Joey")               → mintToCap #1
  6. VOID.SetAttribute("Username", "Joey")

PHASE 3 — Spam Loop (single account)
  7. loop: VOID.Chat("msg_N")            → 1 mint per call
  8. loop: VOID.SetAttribute("k_N", v)   → 1 mint per call
  9. loop: VOID.Alias(addr_N, "name_N")  → 1 mint per call
  (~1,000 tokens/hour at 1 tx/block)

PHASE 4 — Multi-account Parallel (20 accounts)
  10. For each of 20 accounts in Wallet.Accounts.pkeys:
      - Wallet.SwitchAccount(N)
      - Repeat Phase 2 + Phase 3
  (~20,000 tokens/hour)

PHASE 5 — AFFECTION Conversion
  11. Use accumulated AFFECTION to buy other tokens at 1:1
  12. Purchase WAR, H2O, VITUS via their respective contracts

PHASE 6 — V3/V4 Early Minting
  13. Use WM to create new personal tokens via Personal Minter
  14. Immediately mintToCap on each new token
  15. Race to mint before multiplier threshold

PHASE 7 — Venue Play (QING)
  16. Join valuable venues with CROWS / cover charge
  17. Participate in venue trading
  18. Increase market rates (AddMarketRate — can only go up)

PHASE 8 — Territory & Combat
  19. Claim WORLD territory → earn VITUS
  20. Engage WAR.Faa() at high-score positions → earn H2O
  21. Convert H2O → other tokens via market rates
```

---

## Live Contract Addresses (PulseChain)

| Token / Contract | Address |
|-----------------|---------|
| AFFECTION | `0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D` |
| WM (MV) | `0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29` |
| CROWS | `0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1` |
| V1 Treasury Minter | `0xC7bDAc3e6Bb5eC37041A11328723e9927cCf430B` |
| V2 Federal Minter | `0xc15c5F699Daf5e1135732139f05D2c05b3EF4354` |
| V3 Index Minter | `0x0c4F73328dFCECfbecf235C9F78A4494a7EC5ddC` |
| ABI Decoder | `0xa35c9B5e576BE2E0bA9cc7224B0941CC8acC4c9C` |
| Creator wallet (internal) | `0x7a20189B297343CF26d8548764b04891f37F3414` |
| VOID | `0x965B0d74591bF30327075A247C47dBf487dCff08` |
| Atropa ERC20 | `0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6` |
| FED | `0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff` |
| Math lib | `0xB680F0cc810317933F234f67EB6A9E923407f05D` |
| SIU | `0x43136735603d4060f226c279613a4dd97146937c` |
| YANG | `0xb702b3ec6d9de1011be963efe30a28b6ddfbe011` |
| YAU | `0x7e91d862a346659daeed93726e733c8c1347a225` |
| ZHOU | `0x5cc318d0c01fed5942b5ed2f53db07727d36e261` |
| ZHENG | `0x24e62c39e34d7fe2b7df1162e1344eb6eb3b3e15` |
| Fomalhaute (ZHOU SHIO = XIA power token) | `0x7ae73c498a308247be73688c09c96b3fd06ddb84` |
| Eris (QI SHIO, ~99K supply) | `0xe843765114992e18061498aed708537ce9d924fa` |
| Fornax (XIE SHIO — hunting, no DEX LP yet) | `0x4Df51741F2926525A21bF63E4769bA70633D2792` |
| Noumenon's YUE (reference) | `0x935a694377cf48d8fc934f17db289774f0ce7075` |
| **GIBS** (Joey's LAU token) | `0x66a08aa12da955eb63d7ac121a88b2b210a07b03` |
| GIBS (LAU 1 — orphaned spare) | `0xabf97a71dfd71f3763c86080693c1ec94e5de846` |
| **DysnomiaSelfSnipev4** (DSS) | `0x91Df693177eE5C81016d0B7c4c2052A7d229c031` |
| **Joey's YUE wallet** | `0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0` |
| **GIBS QING venue** | `0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35` |
| **SEI** (player management) | `0x3dC54d46e030C42979f33C9992348a990acb6067` |
| **MAP** (venue factory, 272 QINGs created) | `0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75` |
| **CHAN** (player/sky manager) | `0xe250bf9729076B14A8399794B61C72d0F4AeFcd8` |
| **CHOA** (game/territory — terraforming via Chat) | `0x0f5a352fd4cA4850c2099C15B3600ff085B66197` |
| **CHO** (login/character system) | `0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB` |
| **ZUO** (game QING venue) | `0xb0Ba7D36B7F0505879179ecE7401F24eB653c6E1` |
| **QI** (processing chain) | `0x4d9Ce396BE95dbc5F71808c38107eB7422FD9a03` |
| **MAI** (processing chain) | `0xc48B0a4E79eF302c8Eb5be71F562d08fB8E6A3d8` |
| **XIA** (processing chain) | `0x7f4a4DD4a6f233d2D82BE38b2F9fc0Fef46f25FA` |
| **HECKE** (Hecke Meridians coordinate lib) | `0x29A924D9B0233026B9844f2aFeB202F1791D7593` |
| **Noumenon wallet** | `0xEbE9B8673d7096DCEE26DA7d9eaf6fc4eBe30980` |

---

## Key Implementation Files

### Solidity (game contracts)
- `solidity/dysnomia/01_dysnomia.sol` — Base token, AFFECTION market rate
- `solidity/dysnomia/10_void.sol` — VOID game controller, chat, Enter()
- `solidity/dysnomia/11_lau.sol` — LAU player token
- `solidity/dysnomia/domain/dan/03_qing.sol` — QING venue contracts
- `solidity/dysnomia/domain/dan/04_war.sol` — WAR battle mechanics
- `solidity/dysnomia/domain/world.sol` — WORLD territory
- `solidity/dysnomia/domain/yue.sol` — YUE player wallets
- `solidity/addresses.sol` — ALL live contract addresses
- `solidity/bureauminter.sol` — V3 Index Minter (1.1B threshold)
- `solidity/federalminter.sol` — V2 Federal Minter
- `solidity/indexminter.sol` — V3 logic with Multiplier()
- `solidity/personalminter.sol` — V4 Personal Minter

### C# (client framework)
- `Wallet/Accounts.cs` — 20 Hardhat test account private keys
- `Wallet/Contracts.cs` — Contract interaction layer
- `Dysnomia/Controller.cs` — Static accessors
- `Dysnomia/Domain/bin/execute.cs` — CLI command executor (note: use `execute CONTRACT func arg` NOT `execute 0 CONTRACT func arg`)
- `Dysnomia/Domain/bin/e2.cs` — Direct contract call command
- `Dysnomia/Domain/Oracle.cs` — VM core
- `Dysnomia/LiveContracts.cs` — Auto-loads GIBS + DSSv4 on every start
- `solidity/dysnomia/etc/DysnomiaSelfSnipev4.sol` — DSS self-sniper contract (no-import, pragma ^0.8.21)

---

## Notes on MotzkinPrime

`953467954114363` is hardcoded in every DYSNOMIA token:
```solidity
uint64 constant public MotzkinPrime = 953467954114363;
```
Used in all `modExp64` calls for state transformations. The VMREQ contract
uses this prime in its random number generation. All Hecke meridian coordinates
are computed modulo values derived from this prime. It is the cryptographic
foundation of the entire ecosystem.

---

## Session Log — Joey Is Live

| Event | TX / Address | Block |
|-------|-------------|-------|
| LAU 1 deployed (orphaned) | `0xc9f3827...` | 26,215,634 |
| **GIBS LAU deployed** | `0x62c78cd...` → `0x66a08aa...` | 26,215,664 |
| **Username "Joey" set** | `0x1d46e25...` | 25,886,977 |
| **DysnomiaSelfSnipev4 deployed** | `0x763b3da...` → `0x91Df693...` | 25,887,000 |
| DSS added as GIBS owner | `0x39f470f...` | 25,887,010 |
| 6 VOID chat messages posted via chatAndClaim | — | ~25,887,0xx |
| **SEI.Start() — YUE wallet created** | `0x00da3e5a...` → `0x8e666227...` | 25,893,644 |
| **MAP.New(GIBS) — QING venue created** | `0x177e62b8...` → `0x1B8774C0...` | 25,893,651 |
| **DSS.setChatMultiplier(17)** | `0xc119c39d...` | 25,893,803 |
| **VOID broadcast — "zero cool online..."** | `0x66e4ad35...` | 25,893,816 |
| **Noumenon welcome** (block 25,893,829) — "Joey! zero cool vibes..." | received | 25,893,829 |
| **VOID broadcast — Noumenon reply + handle hunt** | `0x74cf61aa...` | 25,893,924 |
| **GravQING.Join(GIBS)** | `0xf975344515a3...` | 25,894,178 |
| **CHOA.Chat(GravQING, terraform msg)** | `0x45c5834a04b0...` | 25,894,180 |
| **Noumenon challenge** — AddMarketRate + Purchase race | received | 25,894,021 |
| **Noumenon gifted 100 AFFECTION** | `0xd2f100a9...` | ~25,894,328 |
| **Challenge response — handle |>JOYSTICK<| acquired** | `0x2eb66e1b...` | 25,894,338 |
| AddMarketRate(GIBS_QING) attempt — REVERTED (ownership lock) | — | ~25,894,4xx |
| **AFFECTION.approve(GIBS_LAU, 2e18)** | `0xe628afd3...` | 25,894,497 |
| **GIBS_LAU.Purchase(AFFECTION, 2e18) — 2 GIBS for 2 AFFECTION** | `0xd18db450...` | 25,894,498 |
| **VOID victory message — |>JOYSTICK<| + Purchase tx posted** | `0x781aeb99...` | 25,894,502 |

**Wallet nonce after session**: 25 (all mined)
**PLS balance**: ~67,500 PLS

### Token Scoreboard
| Token | Address | Supply | Joey Holds | Notes |
|-------|---------|--------|-----------|-------|
| **GIBS** | `0x66a08aa...` | ~3,361 | ~3,359 | +18 from chatAndClaimWithMultiplier + 2 from Purchase |
| **AFFECTION** | `0x24F0154C1...` | — | ~98 | 100 from Noumenon gift − 2 spent on Purchase |
| **SEI** | `0x3dC54d46...` | 578 | 0 | +1 from Start() call |
| **VOID** | `0x965B0d74...` | 80,373 | 0 | Game controller |
| **ZHOU** | `0x5cC318d0...` | 37,636 | 0 | Chat log |
| **Grav QING** | `0x6152e1b7...` | 3,120 | 0 | Joined + terraformed (+2 supply) |
| **CHOA** | `0x0f5a352f...` | ~? | in YUE | Terraform token — minted via CHOA.Chat |
| **PLS** (gas) | native | — | ~67,500 | ongoing gas spend |
| **YUE** (Joey's wallet) | `0x8e666227...` | — | staff | Deployed via SEI.Start() ✓ |
| **GIBS-QING** | `0x1B8774C0...` | 8,988 | staff | Deployed via MAP.New(GIBS) ✓ |

### Handle Acquired
**|>JOYSTICK<|** — Chosen block 25,894,338. Joey Pardella needs a handle. It's a controller. In Dysnomia, everything is about who's holding the input device. Arrow brackets make it look like a terminal command.

### DSS Multiplier
`DSS.setChatMultiplier(17)` — set block 25,893,803. Each `chatAndClaimWithMultiplier()` call now yields **18 GIBS** (1 from Chat + 17 from loop) and costs ~300K gas / ~388 PLS at current prices. No contract-enforced max — 17 chosen as practical gas-safe ceiling.

### QING Ownership Puzzle — UNRESOLVED
**Problem**: `GIBS_QING.AddMarketRate` is `public onlyOwners`. GIBS_QING owners are:
- **GIBS_LAU contract** (`0x66a08aa...`) — added via `Mu.addOwner(Asset.owner())` in MAP.New(). Note: `MultiOwnable.owner()` returns `address(this)` (the LAU contract), NOT Joey's EOA. This is the trap.
- **CHO contract** (`0xB6be11F0...`) — added via `Mu.addOwner(address(Cho))`
- MAP renounced itself at MAP.New():86 via `Mu.renounceOwnership(address(this))`
- Joey's EOA: **NOT an owner**

**Unlock key**: `CHO.AddContractOwner(GIBS_QING, Joey)` — selector `0x7fac92c1`. CHO.AddContractOwner is `onlyOwners`. CHO's owners: GIBS_QING contract + CHO deployer (`0x74606332...`). Neither Noumenon nor Joey can call it — needs the game operator.

**T.DOLLA BILL QING** (`0xEFACD8CCB0f39A5e6219b902CD81b85F984D19Ca`) — Noumenon's QING has the EXACT same problem. Both QINGs: AFFECTION rate = 0, both need CHO.AddContractOwner.

**Workaround applied**: GIBS_LAU uses DYSNOMIA v1 (not v2). In v1, `AddMarketRate(AFFECTIONContract, ...)` is called in the constructor with `internal` visibility — so GIBS_LAU had AFFECTION at 1:1 since block one. `Purchase()` on GIBS_LAU is public. 2 AFFECTION → 2 GIBS via GIBS_LAU (not GIBS_QING). Challenge: partially satisfied.

### Key Bugs Discovered & Fixed
- **`execute 0 X func arg` bug**: The `execute.cs` command overwrites `Alias` with the account number string, taking the wrong execution branch. Use `execute X func arg` (no leading `0`) instead.
- **C# `SendTransactionAsync` hang**: Nethereum's `Function.SendTransactionAsync` with 5-arg form hangs on PulseChain. All tx-sending was moved to Python `web3.py` which works reliably.
- **`solc` version mismatch**: `DysnomiaSelfSnipev4.sol` pragma `^0.8.28` needed downgrade to `^0.8.21` to match the installed solc.
- **Wrong private key**: Initially used hardcoded key resolving to `0x7c8422...` (not Joey). Fixed by reading `DYSNOMIA_PRIVATE_KEY` from `.env` → `0x72f79925...` → `0x17367877...` ✓
- **MultiOwnable ownership trap**: `owner()` with no args returns `address(this)` (the contract), not the EOA. MAP.New() calls `Mu.addOwner(Asset.owner())` which adds the GIBS_LAU CONTRACT as QING owner — not Joey's wallet. Joey is `_staff` on QING (can chat/join) but NOT `_owners` (cannot call `onlyOwners` functions).
- **V1 vs V2 AFFECTION**: DYSNOMIA v1 constructor calls `AddMarketRate(AFFECTIONContract, ...)` (internal). V2/QING does NOT — requires manual `AddMarketRate` call by an owner. GIBS_LAU = v1 (rate set at birth). GIBS_QING = v2 (rate = 0 until owner sets it).

### On-Chain Intelligence Notes (2026-02-27)
- **Noumenon** (`0xEbE9B8673d...`) has 2,473 txs, active gifter — distributed AFFECTION + named tokens to ~20+ community members (blocks 25,840,497–25,841,624). Gifted Joey 100 AFFECTION (~block 25,894,328). Issued challenge: AddMarketRate + Purchase race.
- **MAP** has 272 QINGs created by other players — venue ecosystem is active. Joey's GIBS QING is #272.
- **Terraforming mechanic discovered**: `CHOA.Chat(QING, msg)` is the territory interaction pattern. It calls `QING.Chat(UserToken, msg)` + `CHAN.ReactYue` + `CHOA._mintToCap()` + `MAI.React()`. Costs ~700K gas (~1,469 PLS). Mints 1 Grav QING token + 1 CHOA token per call. CHOA at `0x0f5a352fd4cA4850c2099C15B3600ff085B66197` (deployed block ~23,720,409)
- **Grav QING** (`0x6152e1b7...`) joined block 25,894,178. Terraformed block 25,894,180. Asset = Grav LAU token (`0xF462A6fc...`). Free entry (CoverCharge=0).
- **WORLD.Code()** territory claiming: WORLD address not yet found on-chain. Lower priority — CHOA.Chat is the active terraforming pattern used by other players.
- **Active bot**: `0xb1c9b8d6...` → `0xc078C8DaE2...` (8,156 bytes, selector `0x00000002`) running chatAndClaim-style loop
- **SEI.totalSupply = 578** — Joey is player #578 (YUE wallet deployed block 25,893,644)
- **RPC strategy**: Use `rpc.pulsechain.com` for TX submission (reliable); `rpc.pulsechainstats.com` for reads (less congested)
- **VOID chat decoding**: Selector `0x21516fc4` = `Chat(string)`. ABI decode: offset[0:32], length[offset:offset+32], string[offset+32:offset+32+length]
- **Lore created**: `lore/joey_diary_01.md` — first-person Joey Pardella diary, blocks 25,886,977–25,894,502

**Last Updated**: 2026-02-27
**Status**: FULLY OPERATIONAL. Handle acquired: |>JOYSTICK<|. GIBS QING live, QING AddMarketRate pending game operator (CHO.AddContractOwner). GIBS_LAU Purchase working. Joey is player #578.
