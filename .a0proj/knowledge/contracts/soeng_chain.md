# soeng_chain — On-Chain Processing Order
chain_id: 369 (PulseChain)

Processing order: QI → MAI → XIA → XIE → ZI → PANG → GWAT
Transactions touch these contracts sequentially. Gas estimation must account for the full chain.

| Name | Address                                      | Role |
|------|----------------------------------------------|------|
| QI   | 0x4d9Ce396BE95dbc5F71808c38107eB7422FD9a03   | First in soeng processing chain |
| MAI  | 0xc48B0a4E79eF302c8Eb5be71F562d08fB8E6A3d8   | Second in soeng processing chain |
| XIA  | 0x7f4a4DD4a6f233d2D82BE38b2F9fc0Fef46f25FA   | Third — Charge(), uses Fomalhaute balance |
| XIE  | 0x4Df51741F2926525A21bF63E4769bA70633D2792   | Fourth — Power(), uses Fornax balances. NOTE: XIE ≠ Fornax |
| ZI   | 0xCbAdd3C3957Bd9D6C036863CB053FEccf3D53338   | Fifth — Spin(), uses CHO/Tethys balances |
| PANG | 0xEe25Ccd41671F3B67d660cf6532085586aec8457   | Sixth — Push(), position engine |
| GWAT | (terminal node — address TBD from on-chain)  | Seventh/final in soeng chain |

## SHIO Pairs (soeng)
| SHIO Name  | Address                                      | Notes |
|------------|----------------------------------------------|-------|
| Fomalhaute | 0x7aE73C498A308247BE73688c09c96B3fd06dDB84   | XIA SHIO = XIA.Fomalhaute(), ~50K supply. SHIO funded |
| Fornax     | 0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7   | XIE SHIO = XIE.Fornax(), 50K supply. SHIO funded |
| Eris       | 0xe843765114992e18061498aed708537ce9d924fa   | QI SHIO, ~99K supply |
