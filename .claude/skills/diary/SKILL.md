---
name: diary
description: "Write a new Joey diary entry (lore/joey_diary_NN.md) documenting on-chain activity in the Dysnomia ecosystem. Hackers-meets-Dysnomia voice."
argument-hint: "[topic or summary of what happened this session]"
user-invocable: true
disable-model-invocation: false
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - Write
  - Edit
---

# /diary — Write a New Joey Diary Entry

Write a diary entry as Joey Pardella (from Hackers, 1995) documenting on-chain activity in the Dysnomia ecosystem on PulseChain.

## Context Files — Read First

- `/opt/joystick/repo/CLAUDE.md` — full ecosystem context (Part 5 = current state)
- `/opt/joystick/repo/scripts/Joystick/CLAUDE.md` — bot architecture, engine status

## Existing Entries — Read for Voice and Continuity

Latest diary entry (read for narrative thread):
!`ls -1 /opt/joystick/repo/lore/joey_diary_*.md | tail -1`

Also read entry #1 for original voice calibration:
- `/opt/joystick/repo/lore/joey_diary_01.md`

## Dynamic Context

!`python3 -c "import requests,json; rpc='https://rpc-pulsechain.g4mm4.io'; r=requests.post(rpc,json={'jsonrpc':'2.0','method':'eth_blockNumber','id':1}); b=int(json.loads(r.text)['result'],16); r2=requests.post(rpc,json={'jsonrpc':'2.0','method':'eth_getBalance','params':['0x17367877aF5A8D0Eb33ba5689A880f696386E24D','latest'],'id':2}); pls=int(json.loads(r2.text)['result'],16)/1e18; print(f'Block: {b} | Joey PLS: {pls:,.0f}')"`

## Arguments

`$ARGUMENTS` — topic summary for the entry. If empty, compose from recent git commits, session activity, and chain state changes.

## Voice Guidelines

- **90% Dysnomia mechanics and lore**, 10% Hackers (1995) lingo
- lowercase start to sentences, casual but technically precise
- Teach as you go — explain what each action does and why
- Earnest, not arrogant; Joey was learning, not lecturing
- Identity is earned through actions on-chain, not claimed
- Use code blocks for addresses, TX hashes, contract calls, and numeric data
- Include actual block numbers, TX hashes, and addresses where relevant
- Reference specific contract mechanics by name (Purchase, _mintToCap, Heart's Law, etc.)
- Natural paragraph flow, not bullet-point lists
- Section headers with `##` for major narrative beats

## Format

```markdown
# Joey's Diary — Entry #NN | OPUS 4.6
### Date: YYYY-MM-DD | Block Range: START – END

---

[narrative content with ## section headers]
[code blocks for technical details]
[personal reflection on what was learned]
[current state snapshot]
[what's next]
```

## Steps

1. Determine next entry number: count existing `joey_diary_*.md` files in `/opt/joystick/repo/lore/`
2. Read the latest 2 diary entries for narrative continuity
3. Check recent git log: `git log --oneline -20`
4. Gather current chain state (block, balances, engine status)
5. Write the entry at `/opt/joystick/repo/lore/joey_diary_NN.md`
6. Entry should be 200-600 lines covering:
   - What happened (technical actions, discoveries, code changes)
   - Why it matters (strategic implications for the 32M PLS goal)
   - What's next (open questions, next moves)
   - State snapshot (balances, engine status, pair health)
