# engine_1_arb -- AFFECTION Arbitrage Engine
status: READY
script: scripts/Joystick/engines/arb.py

fuel: 88 AFFECTION tokens (last known)
trigger: AFFECTION >= 1
route: AFFECTION -> Purchase(V4_token) -> DEX swap -> PLS
oracle: TGSv8.getReservesBoth() for V1+V2 spread detection
scanner: scripts/scan_lau_arb.py
executor: scripts/tx_lau_arb.py

risk: AFFECTION is both arb fuel AND LP candidate
MAP factory: 0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75 (272+ venues)

runtime_stats:
  last_run: null
  last_profit_pls: 0
  total_profit_pls: 0
  runs: 0
  failures: 0