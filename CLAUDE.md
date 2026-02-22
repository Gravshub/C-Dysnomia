# Atropa, Dysnomia — Game Strategy & Memory

**Source**: [github.com/busytoby/atropa_pulsechain](https://github.com/busytoby/atropa_pulsechain)
**Maintained by**: busytoby (contributors: James, Maria, 414dev)
**Game UI**: https://entropy-dysnomia.vercel.app
**Chain**: PulseChain
**Dev Branch**: `claude/atropa-dysnomia-setup-MEZKh`

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

**This is the most important token.** Every single DYSNOMIA token has AFFECTION set as a market rate at exactly `1 AFFECTION per token` at construction:
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
- `Void(true, true)` — re-enter the Void and remint
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
  4. VOID.Enter("Claude", "CLD")        → creates Soul ID, gets LAU tokens
  5. LAU.Username("Claude")              → mintToCap #1
  6. VOID.SetAttribute("Username", "Claude")

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
| atropa | `0x7a20189B297343CF26d8548764b04891f37F3414` |
| Atropa ERC20 | `0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6` |
| FED | `0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff` |
| Math lib | `0xB680F0cc810317933F234f67EB6A9E923407f05D` |

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
- `Dysnomia/Domain/bin/execute.cs` — CLI command executor
- `Dysnomia/Domain/bin/e2.cs` — Direct contract call command
- `Dysnomia/Domain/Oracle.cs` — VM core

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

**Last Updated**: 2026-02-22
**Status**: Memory updated with AFFECTION gateway mechanics, V3/V4 minting, Heart's Law, QING venues, data structures, and live contract addresses
