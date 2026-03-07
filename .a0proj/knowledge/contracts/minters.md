# minters -- V1-V4 Treasury Minter Contracts
chain_id: 369 (PulseChain)

| Version | Address | Name | Notes |
|---------|---------|------|-------|
| V1 | 0xC7bDAc3e6Bb5eC37041A11328723e9927cCf430B | TreasuryTokenV1Minter | Root minter. Creates FDIC. Parent of all V2 tokens |
| V2 | 0xc15c5F699Daf5e1135732139f05D2c05b3EF4354 | Federal Minter | Creates treasury tokens backed by parent. Requires WM to fund |
| V3 | 0x0c4F73328dFCECfbecf235C9F78A4494a7EC5ddC | Index/Bureau Minter | Multiplier every 1,111,111,111 tokens minted (global) |
| V4 | 0x394c3D5990cEfC7Be36B82FDB07a7251ACe61cc7 | Personal Minter | Per-token multiplier tied to starting supply |

## V4 CRITICAL RULE
_approve() MUST use type(uint256).max -- NOT the exact amount.
This was the TGSv6 to v7 critical fix. ANY new contract interacting with V4 tokens must follow this pattern.

## V3 Multiplier Formula
Multiplier = ((addition + totalSupply()) / 1111111111000000000000000000) + 1
Every 1,111,111,111 tokens minted globally, cost multiplier increases by 1. Mint early.

## Funding Requirement
WM/MV token required 1:1 as collateral to fund initial supply of any new minter token.
WM address: 0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29
