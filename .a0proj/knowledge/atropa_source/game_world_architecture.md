# game_world_architecture -- Atropa Dysnomia Game World
source: CLAUDE.md

## What is Dysnomia
On-chain game + social platform on PulseChain.
  MMO     -- create LAU character, explore QING venues, claim WORLD territory
  DeFi    -- trade tokens, liquidity pairs, earn via minting
  Social  -- chat logging, user identity, encrypted messaging
  Strategy-- WAR battles, territory control, acronym games
Everything is on-chain and permanent.

## VOID -- The Game Controller
  _activeUsers: address -> Soul uint64
  Enter(name, symbol) -- creates new player (errors if already created)
  Enter()             -- re-enter existing session, refreshes Saat triple
  Chat(message)       -- requires username; logs to ZHOU channel
  Log(message)        -- general logging, triggers mintToCap
  SetAttribute(name, value) -- stores player attributes
  Alias(address, value)     -- creates address-to-name mappings
  AddLibrary(name, address) -- expands game capabilities

## QING -- Venues
  Asset token: what the venue trades
  CoverCharge: fee to join
  Bouncer access via: Staff whitelist OR 25+ CROWS OR (totalSupply/BouncerDivisor) of Asset
  NoCROWS flag: disables CROWS-based access
  GWAT flag (immutable): set at construction based on Luo % 476733977057179 == 0
  Join(UserToken): enter venue, pay cover charge
  chatAndClaim(): mints LAU tokens and claims backing -- primary Engine 2 function

## WAR -- Battle & Resource
  Faa(address Caude, uint256 Position): fetch tail/position score
  Evaluates: modExp(Phoebe, Charge, Meridians(89))
  Generates H2O tokens as battle rewards
  CO2 tracks carbon score (global war metric)

## Hearts Law
  Tokens bonded in a liquidity pair move together in price.
  Market rates can ONLY be increased, never decreased.
  Rate cap: totalSupply / 777 max rate per token
  Solidity: if(Rate < GetMarketRate(Contract)) revert MarketRateCanOnlyBeIncreased(...)