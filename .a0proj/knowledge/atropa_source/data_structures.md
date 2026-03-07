# data_structures -- Core Atropa Protocol Data Structures
source: CLAUDE.md + solidity/dysnomia/include/

## Fa (SHA Cryptographic State)
  uint64 Base, Secret, Signal, Channel, Contour, Pole
  uint64 Identity, Foundation, Element, Coordinate
  uint64 Charge, Chin, Monopole

## Bao (Operation Context)
  address Phi   -- Address reference
  SHA Mu        -- Associated SHA token
  uint64 Xi, Pi -- State values
  SHIO Shio     -- Associated SHIO pair (Rod/Cone)
  uint64 Ring   -- Ring value
  uint64 Omicron, Omega -- Reaction outputs

## User (Player Identity)
  uint64 Soul       -- 64-bit unique user identifier
  Bao On            -- User Bao context
  string Username   -- Display name
  uint64 Entropy    -- User-specific entropy

## Token Supply Pattern
  maxSupply = Xiao.Random() % 111111          -- random cap 0-111110
  originMint = Xiao.Random() % maxSupply / 10  -- ~10% initial mint
  _mint(tx.origin, originMint * 10**18)        -- given to deployer
  _mintToCap() adds exactly 1 token per call until totalSupply == maxSupply

## Soul ID (Saat Triple)
  Three 64-bit values identifying: session, soul position, network aura
  Created by VOID.Enter(name, symbol)