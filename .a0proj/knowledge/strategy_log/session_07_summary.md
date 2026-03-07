# session_07 -- TGSv8 Deployed
source: lore/joey_diary_07.md

Key milestones:
- TGSv8 deployed at 0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32 (block 25,943,194)
- JV8A launched at 0x364793Ea48DEe0b5484F98235ABd1B5f996A0C30 (unminted, intentional)
- PLS balance below 100K buffer -- acknowledged constraint
- Engine 3 native mintWM() eliminates TGSv5 dependency
- getReservesBoth() enables single-call V1/V2 spread detection
- LEARNING: stale balance caused incorrect diary entry -- caught by Grav, corrected
  Rule: always query live RPC before any strategy decision or diary write