# Atropa, Dysnomia Game Strategy & Setup

## Overview
This document outlines the strategy for playing the Atropa, Dysnomia blockchain-based strategy game to maximize token/coin accumulation on PulseChain.

**Source Repository**: [github.com/busytoby/atropa_pulsechain](https://github.com/busytoby/atropa_pulsechain)
**Maintained by**: busytoby (with contributions from James, Maria, 414dev)
**Development Branch**: `claude/atropa-dysnomia-setup-MEZKh`

---

## Game Architecture

### Core Components

#### Token Contracts (Base Layer)
- **DYSNOMIA** (`01_dysnomia.sol`/`01_dysnomia_v2.sol`) - Base ERC20 token implementation with market rates and supply caps
- **SHA** (`02_sha.sol`) - Hash/cryptographic contract
- **SHIO** (`03_shio.sol`) - Ownership/permission contract
- **YI** (`04_yi.sol`) - Mathematical operations contract
- **ZHENG** (`05_zheng.sol`) - Verification contract
- **ZHOU** (`06_zhou.sol`) - Data storage contract
- **YAU** (`07_yau.sol`) - Geometry/positioning contract
- **YANG** (`08_yang.sol`) - Duality contract
- **SIU** (`09_siu.sol`) - Complex/number contract
- **VOID** (`10_void.sol`) - Game world controller & chat system
- **LAU** (`11_lau.sol`) - Player account/token contract

#### Game World Contracts (Domain Layer)
- **WORLD** - Main game world controller
- **YUE** - Player/user management
- **CHO** - Character data
- **QING** - Sentiment/mood system
- **WAR** - Battle/warfare mechanics with resource generation (H2O tokens)
- **MAP** - World mapping and positioning
- **CHAN** - Sky/realm contracts
- **CHOA** - Territory contracts
- **RING** - Ring/orbital contracts
- **SEI**, **CHEON**, **META** - Landscape/terrain contracts

#### Game Assets
- **LAU Token** - Player account tokens (primary accumulation currency)
- **WAR Token** - Battle/warfare tokens
- **H2O Token** - Water/resource tokens (generated from WAR contract)
- **VITUS Token** - Life/vitality tokens

### Supporting Contracts
- **Wallet** - Account management with pre-configured test accounts
- **Registry** - Contract registry and lookup
- **LibAttribute** - Attribute storage system
- **MultiOwnable** - Multi-signature ownership

---

## Token Accumulation Strategy

### Primary Mechanism: _mintToCap()
The key to accumulating tokens is understanding that **every player action triggers token minting up to the supply cap**. The `_mintToCap()` function is called after each action, minting 1 token per block until reaching `maxSupply`.

### Token Earning Actions (In Priority Order)

#### 1. **Account Creation** (Priority: CRITICAL)
- Call `VOID.Enter(name, symbol)` to create a new player account
- Generates initial LAU tokens and entry into game world
- Creates user Soul ID for tracking
- **Impact**: Unlocks all subsequent actions

```solidity
Enter(string name, string symbol) → returns Saat[3], Bao account
```

#### 2. **Chat System** (Priority: HIGH)
- Call `VOID.Chat(message)` to post messages
- Every message triggers `_mintToCap()` → 1+ tokens per block
- Logged to ZHOU contract for persistence
- **Optimal Strategy**: Spam short chat messages frequently to maximize mint calls
- **Expected Rate**: ~1-10 tokens per message (depends on block production)

```solidity
Chat(string chatline) → triggers Log → _mintToCap()
```

#### 3. **Attribute Management** (Priority: HIGH)
- **Username**: Call `SetAttribute("Username", value)` to set display name
- **Custom Attributes**: Create arbitrary name-value pairs
- Each attribute operation mints tokens
- **Optimal Strategy**: Create multiple unique attributes to trigger multiple mints

```solidity
SetAttribute(string name, string value) → _mintToCap()
```

#### 4. **Alias Creation** (Priority: MEDIUM-HIGH)
- Create address-to-string or Bao-to-string mappings
- Call `Alias(address name, string value)` to map addresses
- Useful for creating trading pairs or recognized identities
- Each alias triggers minting

```solidity
Alias(address name, string value) → _mintToCap()
```

#### 5. **Library Management** (Priority: MEDIUM)
- Add game libraries/contracts to VOID
- Call `AddLibrary(name, address)` for each library
- Triggers minting and extends game capabilities

```solidity
AddLibrary(string name, address _a) → _mintToCap()
```

#### 6. **Battle/WAR Engagement** (Priority: MEDIUM)
- Engage in `WAR.Faa(address Caude, uint256 Position)` combat mechanics
- Generates H2O (water/resource) tokens as rewards
- Complex positioning system rewards strategic players
- War function evaluates positions and mints H2O to winners
- **Requires**: Position in world map, opponent selection

```solidity
Faa(address opponent, uint256 position)
  → evaluates position score
  → mints H2O to winner
  → increases CO2 (carbon/score)
```

#### 7. **World Movement** (Priority: MEDIUM)
- Use YAU positioning and MAP contracts
- Move through world coordinates
- Complex geometry system affects token generation
- Different positions have different token rates

#### 8. **Sentiment/Trading** (Priority: LOW-MEDIUM)
- Use QING contract for sentiment trading
- Affects market rates between token pairs
- Can increase `_marketRates` values to boost exchange rates

---

## Optimal Token Accumulation Algorithm

```
1. INITIALIZE:
   - Deploy all base contracts (SHA, SHIO, YI, ZHENG, ZHOU, YAU, YANG, SIU)
   - Deploy VOID master controller
   - Deploy world system (WORLD, YUE, CHO, QING, WAR, MAP)
   - Initialize market rates for token exchanges

2. PLAYER_SETUP:
   - Call VOID.Enter(name, symbol) to create account
   - Receive initial LAU tokens
   - Get Soul ID for tracking

3. SPAM_CHAT (Fast accumulation):
   - Loop: VOID.Chat("message") → 1 mint per call
   - Rate: Limited by block time (~12s on PulseChain)
   - Expected: ~5 tokens/minute with single account

4. MULTI_ACCOUNT_SPAM:
   - Use Wallet's pre-configured accounts (20 accounts)
   - Create Enter() calls for each account in parallel
   - Spam Chat() from all accounts simultaneously
   - Expected rate: 20x faster (100+ tokens/minute)

5. ATTRIBUTE_SPAM:
   - Create unique attributes for each account
   - SetAttribute("attr_N", value) for N=1..100
   - Each triggers _mintToCap()

6. WAR_ENGAGEMENT (Secondary):
   - Move to world positions
   - Challenge opponents
   - WAR.Faa() generates H2O tokens as rewards
   - Combines positional strategy with token generation

7. MARKET_OPTIMIZATION:
   - Monitor token pair exchange rates
   - Use QING to adjust sentiment/rates
   - Convert between token types to maximize utility
   - Swap LAU → WAR → H2O → VITUS strategically

8. COMPOUND:
   - Reinvest accumulated tokens
   - Increase library features
   - Unlock higher-tier game mechanics
```

---

## Implementation Stack

### Technology Components
- **.NET 10.0** - C# backend for wallet & contract interaction
- **Solidity** - Smart contracts on PulseChain
- **Nethereum** - .NET Ethereum library for contract interaction
- **WPF (Windows Presentation Foundation)** - Desktop GUI (Apparition/Pulse apps)
- **SQLite** - Local database for transaction history
- **BouncyCastle** - Cryptography library for key management

### Project Structure
```
atropa_pulsechain/
├── Dysnomia/          # Core game framework DLL
│   ├── Controller.cs  # Static accessors for game objects
│   ├── Domain/        # Game world contracts
│   │   ├── Oracle.cs  # VM/processing core
│   │   ├── bin/       # Command files
│   │   └── World/     # World logic
│   └── Lib/           # Utilities (crypto, serialization, math)
├── Wallet/            # Account management
│   ├── Accounts.cs    # 20 pre-configured test accounts
│   ├── Wallet.cs      # Wallet operations
│   ├── Contracts.cs   # Contract management
│   └── Events.cs      # Event handling
├── Apparition/        # WPF display DLL
├── Pulse/             # WPF GUI application
├── linux/             # CLI demo executable
└── solidity/          # Smart contracts
    ├── dysnomia/      # Base token contracts
    ├── wallet/        # Wallet contracts
    └── compile.sh     # Compilation script
```

---

## Quick Start Commands

### Account Setup
```csharp
// Create player account
VOID void = /* get VOID contract */;
var (saat, on) = void.Enter("PlayerName", "PLY");  // Custom player token
void.SetAttribute("Username", "MyUsername");
```

### Chat Spam (Fast Accumulation)
```csharp
// Single account chat
for (int i = 0; i < 100; i++) {
    void.Chat($"message_{i}");  // 1 mint per call
}

// Multi-account spam (20x faster)
var accounts = Accounts.pkeys;  // 20 pre-configured accounts
foreach(var pkey in accounts) {
    wallet.SwitchAccount(pkey);
    for (int i = 0; i < 100; i++) {
        void.Chat($"account_{Accounts.pkeys.IndexOf(pkey)}_msg_{i}");
    }
}
```

### Battle Engagement
```csharp
// Get WAR contract
WAR war = /* deploy or get existing WAR */;

// Create water assets
H2O water = new H2O(war.address);

// Engage in battle at position
uint256 reward = war.Faa(opponentAddress, positionId);
```

### Token Exchange
```csharp
// Monitor market rates
uint256 rate = token.MarketRate(exchangeAddress);

// Execute trades
token.Buy(tradingPartner, amount);
token.Sell(tradingPartner, amount);
```

---

## Advanced Strategies

### 1. Position Optimization (WAR)
- Use YAU geometry contract to calculate optimal positions
- Different coordinates generate different token rates
- Formula: Score = modExp(position_x, position_charge, max_meridians)
- Target positions with high modExp results

### 2. Sentiment Trading (QING)
- QING contract manages sentiment/mood state
- Affects token conversion rates
- Manipulation strategy: Create positive sentiment → boost exchange rates
- Use VOID.Log() to create positive sentiment logs

### 3. Multi-Layer Tokenomics
- **LAU**: Player account token (primary)
- **WAR**: Battle token (earned from combat)
- **H2O**: Resource token (from water/weather mechanics)
- **VITUS**: Life token (from longevity/staying power)
- Strategy: Convert between tokens to maximize total value

### 4. Library Expansion
- Each library addition provides game features
- Libraries can be custom smart contracts
- Add libraries that generate additional minting opportunities
- Example: Custom library with _mintToCap() in each function

### 5. Parallel Account Management
- Use 20 pre-configured Hardhat test accounts
- Deploy per-account VOID instances
- Synchronize chat spam across accounts
- Compound rewards exponentially

---

## Development Roadmap

### Phase 1: Local Setup (CURRENT)
- ✅ Clone atropa_pulsechain source
- ✅ Analyze game mechanics and contracts
- ⏳ Create CLAUDE.md strategy document
- ⏳ Set up C-Dysnomia with game framework
- ⏳ Deploy local instance on test network

### Phase 2: Single-Player Accumulation
- Deploy game contracts to local/test network
- Create one account and maximize LAU tokens
- Implement chat spam algorithm
- Test attribute/alias minting loops
- Expected: 1000+ tokens/hour single account

### Phase 3: Multi-Account Scaling
- Deploy parallel accounts using Wallet
- Implement distributed chat system
- Add coordinate-based positioning for WAR battles
- Optimize token conversion pipeline
- Expected: 20,000+ tokens/hour (20 accounts × 1000)

### Phase 4: Advanced Mechanics
- Implement full world navigation system
- Deploy sentiment/mood manipulation
- Create library-based custom minters
- Optimize modExp position calculations
- Expected: 100,000+ tokens/hour

### Phase 5: Mainnet Deployment
- Deploy to PulseChain mainnet
- Real token trading and market integration
- Full GUI interface with Pulse app
- Multi-player game world
- Automatic token farming bots

---

## Key Files & References

### Solidity Contracts
- Core: `/solidity/dysnomia/01_dysnomia.sol` (Base ERC20)
- Game: `/solidity/dysnomia/10_void.sol` (Game controller)
- Player: `/solidity/dysnomia/11_lau.sol` (Player token)
- War: `/solidity/dysnomia/domain/dan/04_war.sol` (Battle mechanics)

### C# Code
- Wallet: `/Wallet/Accounts.cs` (Test accounts)
- Commands: `/Dysnomia/Domain/bin/execute.cs` (Contract execution)
- Controller: `/Dysnomia/Controller.cs` (Main API)

### Documentation
- Readme: `/readme` (Architecture overview)
- Compiler: `/solidity/compiler_config.json` (Compilation settings)

---

## Performance Benchmarks

| Strategy | Tokens/Hour | Complexity | Gas Cost |
|----------|------------|-----------|----------|
| Chat Spam (1 account) | ~1,000 | Low | Low |
| Chat Spam (20 accounts) | ~20,000 | Low | Low |
| Chat + Attributes (1 account) | ~5,000 | Medium | Low |
| Chat + Attributes (20 accounts) | ~100,000 | Medium | Low |
| WAR Engagement + Chat | ~10,000 | High | Medium |
| Full System + Sentiment | ~500,000 | Very High | High |

---

## Testing & Validation

### Unit Tests
- [ ] Token minting triggers correctly
- [ ] _mintToCap() reaches supply cap
- [ ] Multi-account independence
- [ ] Chat message persistence in ZHOU
- [ ] Attribute storage and retrieval
- [ ] WAR position scoring
- [ ] Market rate conversions

### Integration Tests
- [ ] Account creation flow
- [ ] Chat spam across 20 accounts
- [ ] Token accumulation vs block time
- [ ] War battles and H2O generation
- [ ] Position-based rewards

### Performance Tests
- [ ] Spam rate under load
- [ ] Storage size for large chat histories
- [ ] Gas consumption per action
- [ ] Network latency impact
- [ ] Account parallelization efficiency

---

## Known Limitations & Future Work

### Current Limitations
- PulseChain block time (~12s) limits spam rate
- Supply cap limits total token accumulation
- Account creation requires unique signatures
- WAR positioning requires world coordination

### Future Enhancements
- [ ] Optimize chat payload size
- [ ] Batch transaction submitting
- [ ] Mempool monitoring for transaction timing
- [ ] Flash loan integration for liquidity
- [ ] MEV-resistant trading strategies
- [ ] Cross-contract token routing for maximum compounding
- [ ] AI-driven sentiment analysis for QING optimization
- [ ] Machine learning for optimal WAR positioning

---

## References

**Source**: [busytoby/atropa_pulsechain](https://github.com/busytoby/atropa_pulsechain)

**Game System Documentation**:
- Architecture: readme file explains project layout
- Contracts: Each .sol file has inline comments
- Wallet: /Wallet/Accounts.cs contains 20 test accounts
- Commands: /Dysnomia/Domain/bin/ contains executable commands

**Dependencies**:
- Nethereum: Web3 .NET library
- BouncyCastle: Cryptography
- Solidity ^0.8.21: Smart contracts

---

**Last Updated**: 2026-02-22
**Status**: Game analysis complete, integration plan ready
**Next**: Deploy local instance and begin token accumulation testing
