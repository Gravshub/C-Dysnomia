# engine_4_beat -- META.Beat() Territory Engine
status: RUNNING
script: scripts/Joystick/engines/beat.py
primary_script: scripts/tx_full_beat_flow.py

dione: 41 (block counter toward reward threshold)
shio_funded: Fornax=0.15, Fomalhaute=0.001387, CHO=0.002921

call_order: CHEON.Su() -> META.Beat()
META: 0xE77Bdae31b2219e032178d88504Cc0170a5b9B97
CHEON: 0x3d23084cA3F40465553797b5138CFC456E61FB5D

blocker: WORLD contract not yet deployed -- Beat reward path incomplete
note: Beat increments Dione but full reward cycle needs WORLD

runtime_stats:
  last_run: null
  dione: 41
  charge: 0
  deimos: 0
  yeo: 0
  runs: 0