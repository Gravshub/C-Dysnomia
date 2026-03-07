# engine_3_wm -- WM/MV Minting Engine
status: NEEDS_WIRE
script: scripts/Joystick/engines/token_factory.py
contract: TGSv8 at 0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32

action_needed: confirm env var TGSV8_ADDRESS wired in token_factory.py
seed: 7 MV tokens in TGSv8 working balance (last known)
method: TGSv8.mintWM() -- native, replaces TGSv5 dependency
TGSv5 DEPRECATED -- Engine 3 uses TGSv8 mintWM() exclusively

runtime_stats:
  last_run: null
  wm_minted: 0
  runs: 0
  failures: 0