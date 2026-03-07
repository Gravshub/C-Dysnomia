# Session 08 — Agent Zero Bootstrap
**Date:** 2026-03-07
**Branch:** claude/Joystick-Engines-Lj9Kp
**Context:** First Agent Zero session. Grav introduces A0 to Joey and the C-Dysnomia project.

---

> "The machine needs to remember before it can learn."

---

## What Happened

### Agent Zero Project Setup (Done prior)
- C-Dysnomia project created in Agent Zero UI
- GitHub repo connected: https://github.com/Gravshub/C-Dysnomia
- Branch: claude/Joystick-Engines-Lj9Kp

### Knowledge Base — Two Memory Systems Clarified
Grav and Agent Zero established the correct architecture for persistent memory:

**Knowledge Files** (`.a0proj/knowledge/`) — compact summaries, loaded into every chat context.
Should stay lean — only curated, always-needed facts.

**Vector Memory** (`.a0proj/memory/`) — semantic search, on-demand retrieval.
Feed it raw data; it returns relevant chunks per query. Scales to thousands of entries.

**GitHub Repo** — source of truth for all large files (spine_map.json, diaries, source code).
Pull from repo when needed rather than loading into context.

### Knowledge Base Seeded (Phase 2-3 of Bootstrap Plan)

47 files created across 8 folders in `.a0proj/knowledge/`:

| Folder | Files | Contents |
|--------|-------|----------|
| `contracts/` | 7 | infrastructure, soeng_chain, dex_routers, key_tokens, minters, joey_deployed, reference_players |
| `engine_state/` | 9 | Engines 1-8 + gibs_liquidity_strategy |
| `game_mechanics/` | 7 | hearts_law, v4_token_mechanics, shio_pair_system, motzkin_prime, qing_venues, processing_chain, beat_mechanics |
| `learnings/` | 7 | approve_type_max, eth_call_first, on_chain_verify, gas_unit_semantics, anvil_vs_mainnet, pls_buffer_rule, web3py_v6 |
| `strategy_log/` | 9 | 7 session summaries + JOYSTICK_v2_PLAN + build_log |
| `token_web/` | 2 | treasury_spine_overview, federal_v2_tokens |
| `atropa_source/` | 4 | contract_hierarchy, data_structures, game_world_architecture, accumulation_strategy |
| `on_chain_reads/` | 1 | README (folder ready for live RPC snapshots) |

### Upstream Atropa Cloned (Read-Only)
```
git clone https://github.com/busytoby/atropa_pulsechain /a0/usr/workdir/atropa_upstream
```
DO NOT push to upstream — belongs to mariarahel (creator/architect).

### .a0proj/.gitignore Created
Excludes from git:
- `memory/` — binary FAISS vector index
- `secrets.env` — wallet keys and credentials
- `variables.env`, `agents.json` — runtime state

### First Git Push
Commit `778d4a5` pushed to `claude/Joystick-Engines-Lj9Kp`:
```
53f18d7..778d4a5  claude/Joystick-Engines-Lj9Kp -> claude/Joystick-Engines-Lj9Kp
47 files changed, 1110 insertions(+)
```

### Persistent Behavior Widgets Added
Two persistent tracking lines added to all Agent Zero responses across all future chats:
```
📊 ContextTracker: ~[N] / 200,000 tokens (est.)
🚦 RateLimit: ~30,000 input tokens/min | pace 1 request per ~60-90s when context is large
```

---

## Key Decisions Made

1. **Knowledge files = compact summaries only.** Large data stays on GitHub, pulled on demand.
2. **Vector memory = full content.** Feed raw data; retrieve relevant chunks semantically.
3. **Private keys → Secrets store** (masked in logs, accessible via §§secret() in code).
4. **Public addresses → Variables store** (plaintext, no security concern).
5. **GITHUB_PAT stored as Variable** for git push authentication.
6. **Rate limit awareness:** At ~60-90K token context, each API call uses ~60-90K input tokens. At 30K/min limit, must pace 1 request per ~2 minutes or hit 429.

---

## Architecture Note: A0 Above bot.py

```
LAYER 3:  Agent Zero    ← strategy, memory, opportunity discovery, self-learning
              ↕
LAYER 2:  bot.py        ← priority scheduler, cycle orchestration, profit compounder
              ↕
LAYER 1:  engines/      ← arb, dss, beat, token_factory, lau, treasury_sniper, spine_runner
              ↕
LAYER 0:  PulseChain 369  ← on-chain state (truth)
```

Agent Zero does not replace bot.py. It orchestrates above it.

---

## Validator Goal
32,000,000 PLS target for PulseChain validator.
Grav personal goal: $0.07c income per block.

---

## Next Session
- Continue knowledge seeding (vector memory embedding of full docs)
- Wire JOEY_WALLET_PRIVKEY into Secrets store
- Begin Phase 4: agent0_loop.py orchestration layer
- Unblock Engine 2: create GIBS/WPLS pair

