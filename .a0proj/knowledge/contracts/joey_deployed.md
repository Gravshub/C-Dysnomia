# joey_deployed -- Joey Deployed Contracts
chain_id: 369 (PulseChain)
Owner: 0x17367877aF5A8D0Eb33ba5689A880f696386E24D

## TGSv8 -- Primary Execution Contract (ACTIVE)
address: 0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32
deployed_block: 25,943,194
status: verified, paused=false, authorized=true
capabilities: mintWM, atomicArb, executeRoute, addLiquidity, batchClaimTreasury, batchMintAndClaim, getReservesBoth
notes: getReservesBoth() enables single-call V1+V2 spread detection. Engine 3 uses native mintWM() -- TGSv5 no longer needed.

## JV8A -- V4 Treasury Token (DEPLOYED, UNMINTED -- INTENTIONAL)
address: 0x364793Ea48DEe0b5484F98235ABd1B5f996A0C30
type: V4_TREASURY
deployed_block: 25,943,266
total_supply: 0
parent: TGSv8
status: Unminted. Strategic -- awaiting mint strategy decision.

## GIBS (Gibson) -- LAU Token
address: 0x66a08aa12da955eb63d7ac121a88b2b210a07b03
type: LAU
balance: 3,395 GIBS (as of block 25,950,721)
dex_pairs: NONE -- Engine 2 blocker
intrinsic_floor: 52.25 PLS (via 1:1 AFFECTION purchase rate)
target_pair_price: 50 PLS/GIBS for GIBS/WPLS on PulseX V1
unblock_action: seed pair ~161 GIBS + 8,054 WPLS at 50 PLS/GIBS
expected_revenue: +512 PLS net per chatAndClaim cycle (18 GIBS)
payback_period: ~15 DSS calls to recover LP seed
GIBS QING venue: 0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35
GIBS spare (orphaned): 0xabf97a71dfd71f3763c86080693c1ec94e5de846

## DSS -- DysnomiaSelfSnipev4
address: 0x91Df693177eE5C81016d0B7c4c2052A7d229c031
type: Self-sniper contract
status: active

## TGSv7 (SUPERSEDED)
address: 0x82E8B7e24bD9f0b389e94ddB8714B001a58e387d
status: superseded -- do not use

## TGSv5 (DEPRECATED)
address: 0xeeB330d3419193b4E42507fA07CcF2fC681a6127
status: DEPRECATED. Any TGSv below v8 is no longer used.

## Wallets
Joey EOA: 0x17367877aF5A8D0Eb33ba5689A880f696386E24D
Joey YUE: 0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0
