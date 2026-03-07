# dex_routers — PulseX DEX Infrastructure
chain_id: 369 (PulseChain)

| Name               | Address                                      | Notes |
|--------------------|----------------------------------------------|-------|
| PulseX V1 Router   | 0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02   | Primary arb router — use for AFFECTION→token swaps |
| PulseX V2 Router   | 0x165C3410fC91EF562C50559f7d2289fEbed552d9   | Secondary router |
| PulseX V1 Factory  | 0x1715a3E4A142d8b698131108995174F37aEBA10D   | Pair discovery for V1 |
| PulseX V2 Factory  | 0x29eA7545DEf87022BAdc76323F373EA1e707C523   | Pair discovery for V2 |

## Notes
- tx_acquire_shio_p2.py uses V1 router (V1 fix over original p1 script)
- TGSv8.getReservesBoth() fetches V1+V2 reserves in a single call
- Always check both V1 and V2 spreads before routing
