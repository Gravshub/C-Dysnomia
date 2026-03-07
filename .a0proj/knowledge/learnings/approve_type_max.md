# approve_type_max

V4 treasury tokens charge 2x MV cost ratio on mint. _approve() MUST use type(uint256).max not the exact amount. This was the critical TGSv6→v7 fix. ANY new contract interacting with V4 tokens must follow this pattern.
