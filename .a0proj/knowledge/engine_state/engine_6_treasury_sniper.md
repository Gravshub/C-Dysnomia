# engine_6_treasury_sniper -- Treasury Sniper Engine
status: IMPLEMENTED
script: scripts/Joystick/engines/treasury_sniper.py

function: Scans treasury spines for claimable backing, executes claim
targets: V2 Federal tokens with debenture flag open
data_source: data/v2_federal_tokens.json (14 tokens tracked)

known_targets_with_balance:
  BAR  0xaAE18Cd46C45d343BbA1eab46716B4D69d799734  selfBal=11288T  est ~1.15M PLS
  FDIC 0x812571A12330A74E2A3C1fF8953f6f3aac7a83e9  selfBal=14330T  high pls/token
  SCOIETY 0xDb4eBEAfb23eCA5275821aB0D87c7f6fa5514EA4  selfBal=148845T
  OZZY 0x52b4F56d87765E7A9567E35bea97de13C3386554  debenture=TRUE claiming open
  PARADE 0xE37ACc54711562510FaFC45d8199Ee329ebBceDd  DEX spread 3392% observed

note: All 14 tokens need on-chain Debenture() check before claiming

runtime_stats:
  last_run: null
  total_claimed_pls: 0
  runs: 0
  failures: 0