# on_chain_verify_before_write

Never use assumed or stale balances. Always query live RPC before any strategy decision or diary entry. A wrong balance led to an incorrect diary entry in session 7 — caught by Grav, corrected.
