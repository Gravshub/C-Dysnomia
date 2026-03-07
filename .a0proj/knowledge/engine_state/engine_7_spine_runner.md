# engine_7_spine_runner -- Spine Runner Engine
status: IMPLEMENTED
script: scripts/Joystick/engines/spine_runner.py

function: Traverses treasury spines minting along each hop
data_source: data/spine_map.json (890 spines, 1282 tokens)
longest_spine: 23 hops (FED->NASDOQ->SKILL->...->KENICKIE)
root_token: FED at 0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff
maria_spines: 466 of 890 total

runtime_stats:
  last_run: null
  total_minted_pls: 0
  iterations: 0
  failures: 0