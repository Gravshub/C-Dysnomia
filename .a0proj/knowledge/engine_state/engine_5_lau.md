# engine_5_lau -- LAU Token Cycle Engine
status: IMPLEMENTED
script: scripts/Joystick/engines/lau.py

cycle: Alpha -> Beta -> Upsilon -> Pi -> Rho -> Upsilon
pls_gate: triggers when PLS balance < 150K PLS

shio_states:
  Alpha: first-minted SHIO
  Beta: second-minted SHIO
  Upsilon: Rho reward
  Pi: Cone emission
Rho_function: cycles Cone -> Rod
See shio_pair_system in game_mechanics/ for full details