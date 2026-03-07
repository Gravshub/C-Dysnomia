# key_tokens — Strategic Token Addresses
chain_id: 369 (PulseChain)

## Gateway & Utility
| Symbol    | Address                                      | Role |
|-----------|----------------------------------------------|------|
| AFFECTION | 0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D   | Universal gateway — 1 AFFECTION mints ANY token at 1:1 via Purchase() |
| WM / MV   | 0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29   | Required 1:1 collateral to fund initial supply of any new minter token |
| CROWS     | 0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1   | Social credential — 25 CROWS = bouncer access to any non-NoCROWS QING venue |
| WITHOUT   | 0x173216Ed67eBF3E6767D86e8b3Ff32e0d64437bF   | Ban token — Joey MUST hold 0 of this token |

## Protocol Root Tokens
| Symbol  | Address                                      | Role |
|---------|----------------------------------------------|------|
| ATROPA  | 0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6   | Atropa ERC20 base token |
| FED     | 0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff   | Root of deepest treasury spine (23 hops: FED→NASDOQ→SKILL→...→KENICKIE) |
| TBILL   | 0x463413c579D29c26D59a65312657DFCe30D545A1   | Treasury Bill contract |

## Joey's LAU Token
| Symbol | Address                                      | Role |
|--------|----------------------------------------------|------|
| GIBS   | 0x66a08aa12da955eb63d7ac121a88b2b210a07b03   | Gibson — Joey's LAU token. 3,395 GIBS held. No DEX pair yet (Engine 2 blocker) |
| GIBS-2 | 0xabf97a71dfd71f3763c86080693c1ec94e5de846   | LAU 1 — orphaned spare, not primary |

## Constants
| Name         | Value                  | Notes |
|--------------|------------------------|-------|
| MotzkinPrime | 953467954114363        | Universal prime modulus for all cryptographic state transforms |
| Gua          | 1652929763764148448182513644633101239607891671119935657884642 | Universe constant in CHO |
| V3 Threshold | 1,111,111,111 tokens   | Multiplier increases every time this much is minted (global) |
