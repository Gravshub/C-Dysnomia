# contract_hierarchy -- Atropa Protocol Contract Layer Map
source: CLAUDE.md + busytoby/atropa_pulsechain
chain: PulseChain 369

## Core Infrastructure
  VMREQ   -- Random number generation (modExp-based)
  DYSNOMIA -- Base ERC20 + market rates
  SHA     -- Cryptographic state token
  SHIO    -- Rod/Cone paired token system
  YI      -- DeFi orchestration
  ZHENG   -- Rod/Cone installation manager
  ZHOU    -- Market rate orchestrator / chat log
  YAU     -- Protocol coordinator
  YANG    -- Multi-state aggregator
  SIU     -- Token generation with Aura identity
  VOID    -- User session & chat management
  LAU     -- User interface / player account

## Domain: dan/
  CHO     -- Login / character system
  QING    -- Venues (chatrooms, marketplaces)
  WAR     -- Battle mechanics, H2O reward generation

## Domain: sky/
  CHAN    -- Player/sky management
  CHOA   -- Game/territory
  RING   -- Time/orbital mechanics

## Domain: soeng/ (Processing Chain)
  QI -> MAI -> XIA -> XIE -> ZI -> PANG -> GWAT

## Domain: tang/
  SEI    -- Player management
  CHEON  -- Landscape/terrain
  META   -- Meta-player management (Beat function)

## World
  MAP    -- World coordinate system (Hecke Meridians)
  WORLD  -- Territory ownership and rewards (NOT YET DEPLOYED)
  YUE    -- Player wallet management

## Assets
  H2O    -- Water token (WAR battle rewards)
  VITUS  -- Life token (territory/creator rewards)

## Libraries
  MultiOwnable  -- Multi-owner access control
  Registry      -- Key-value storage
  Encrypt       -- User-to-user encrypted messaging
  StringLib     -- String manipulation
  HeckeMeridians-- Geographic coordinate system
  ReactionsCore -- Entropy-based reactions
  Attribute     -- User attribute storage