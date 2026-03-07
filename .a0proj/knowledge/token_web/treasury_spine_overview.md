# treasury_spine_overview

890 treasury spines mapped. 466 are maria spines. Longest spine = 23 tokens.
Root token FED (0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff) anchors deepest spine:
FED -> NASDOQ -> SKILL -> LARP -> ... -> KENICKIE (23 hops)
Each hop is a mint/claim opportunity.

Total tokens in web: 1,282
Data: scripts/Joystick/data/spine_map.json (29,973 lines, 890 spines)
Token master: scripts/Joystick/data/token_master.json

Opportunity Ranking Criteria:
1. Claimable backing depth (PLS value)
2. Current DEX spread (arb gap)
3. Gas cost to traverse
4. Debenture flag status (is Claim still open?)

Key addresses:
  FED root: 0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff
  AFFECTION gateway: 0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D
  MAP factory: 0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75