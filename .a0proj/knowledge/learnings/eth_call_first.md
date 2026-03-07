# eth_call_first

Every transaction must be simulated via eth_call before broadcast. estimate_gas() must succeed — if it reverts, the TX would revert on-chain. Never send blind. 1.3x gas multiplier is standard.
