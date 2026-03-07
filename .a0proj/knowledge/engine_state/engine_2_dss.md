# engine_2_dss -- DysnomiaSelfSnipe Engine
status: BLOCKED
script: scripts/Joystick/engines/dss.py
contract: DSS at 0x91Df693177eE5C81016d0B7c4c2052A7d229c031

blocker: GIBS/WPLS PulseX pair does not exist
unblock_action: seed pair ~161 GIBS + 8054 WPLS at 50 PLS/GIBS
creation_script: scripts/tx_create_gibs_wpls_pair.py
expected_revenue: +512 PLS net per chatAndClaim cycle (18 GIBS)
payback_period: ~15 DSS calls to recover LP seed

cycle: chatAndClaim() in GIBS QING -> mints LAU tokens -> claims backing
GIBS QING: 0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35

runtime_stats:
  last_run: null
  last_profit_pls: 0
  total_profit_pls: 0
  runs: 0
  failures: 0