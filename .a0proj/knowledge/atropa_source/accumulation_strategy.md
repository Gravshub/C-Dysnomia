# accumulation_strategy -- Token Accumulation Strategy
source: CLAUDE.md

## Priority Stack
  1. AFFECTION  -- universal gateway, 1:1 into every token via Purchase()
  2. WM/MV      -- required to create new tokens (1:1 collateral)
  3. 25 CROWS   -- bouncer access to any non-NoCROWS venue
  4. Create LAU -- VOID.Enter(name, symbol) -> Soul ID, SHIO reactor, YUE wallet
  5. Spam mintToCap triggers -- every game action mints 1 token
  6. V3/V4 early minting -- mint before multiplier increases
  7. Territory + WAR -- WORLD (not deployed), WAR.Faa() -> H2O

## mintToCap Triggers (gas-efficient)
  VOID.Chat(msg)            -- 1 mint per call, low gas
  LAU.Username(str)         -- 1 mint per call, low gas
  VOID.SetAttribute(k, v)   -- 1 mint per call, low gas
  VOID.Alias(addr, str)     -- 1 mint per call, low gas
  VOID.AddLibrary(name, addr) -- 1 mint per call, medium gas
  LAU.Void(true, true)      -- re-enter void, medium gas
  VOID.Log(str)             -- 1 mint per call, low gas

## Multi-Account Strategy
  Wallet has 20 pre-configured test accounts (Wallet/Accounts.cs)
  Run all actions in parallel across accounts for 20x throughput

## AFFECTION Conversion
  Use Purchase(token_address, amount) on any DYSNOMIA token
  Converts AFFECTION to target token at 1:1 rate
  Strategy: accumulate AFFECTION -> purchase spread targets -> arb on DEX

## V4 Personal Minter Cycle
  1. Acquire WM tokens
  2. Deploy new V4 token via Personal Minter (0x394c3D5990...)
  3. MUST _approve(type(uint256).max) -- not exact amount
  4. mintToCap immediately before others find token
  5. Race against multiplier threshold