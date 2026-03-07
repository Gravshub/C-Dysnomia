# on_chain_reads/

This folder contains timestamped RPC query results.
NEVER use stale data -- always query live RPC before strategy decisions.

Format: YYYY-MM-DD_HH-MM_<description>.md
Example: 2026-03-07_05-00_pls_balance.md

Rule: on_chain_verify_before_write
  Never assume or use stale balances.
  A wrong balance led to an incorrect diary entry in session 7 -- caught by Grav.