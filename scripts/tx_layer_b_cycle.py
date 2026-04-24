#!/usr/bin/env python3
"""
tx_layer_b_cycle.py — DFM → PARADE Treasury Cycle (Layer B)

Stage 2 of the FDIC→DFM→PARADE cascade. Cycle uses 5 self-deployed ammo
(幹B01-B05, Parent=DFM, Debenture=true) to pump DFM into PARADE (Maria's
pre-existing V2 Federal token whose Parent is DFM).

Phases:
  --phase approve    Static MAX approvals (WM→V2Minter if needed, DFM→PARADE)
  --phase deploy     Deploy 5 幹B ammo (Parent=DFM) + DFM→ammo + ammo→PARADE
  --phase probe      1-unit sanity: PARADE.mint(1) + PARADE.Claim(幹B01, 1)
  --phase cycle      One 11-TX batch (PARADE.mint(5N) + 5×ammo.mint(N) + 5×Claim(N-K))

Flags:
  --n <int>          Tokens per round for cycle phase (default 10)
  --hold-back <int>  Retain this many of each ammo during Claim phase (default 0)
  --dry-run          eth_call simulate every TX, submit nothing
  --yes              Skip per-phase interactive confirmation
  --verify           Print balances + ammo state + allowances, exit

Plan: /home/joey/.claude/plans/nested-noodling-garden.md
"""

import argparse
import json
import os
import sys
import time
from typing import Optional

from eth_abi import encode as abi_encode
from eth_abi import decode as abi_decode
from web3 import Web3
from web3.exceptions import ContractLogicError

# ─── Addresses (checksummed) ─────────────────────────────────────────────
JOEY     = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
DFM      = Web3.to_checksum_address("0x51160F352ED148C89d48dfe6384Edd07aFA24E0E")
PARADE   = Web3.to_checksum_address("0xE37ACc54711562510FaFC45d8199Ee329ebBceDd")
WM       = Web3.to_checksum_address("0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29")
V2MINTER = Web3.to_checksum_address("0xc15c5F699Daf5e1135732139f05D2c05b3EF4354")

# ─── Constants ───────────────────────────────────────────────────────────
CHAIN_ID       = 369
GAS_MULT       = 2.5
GAS_PRICE_CEIL = 2_000_000 * 10**9      # 2M Gwei in wei
PLS_FLOOR      = 100_000 * 10**18        # 100K PLS gas floor
MAX_UINT256    = (1 << 256) - 1
PRIORITY_FEE   = 100_000 * 10**9         # 100K Beats priority tip (avoids stuck TX on PulseChain)

READ_RPC   = os.environ.get("PULSECHAIN_READ_RPC", "https://rpc-pulsechain.g4mm4.io")
SUBMIT_RPC = os.environ.get("PULSECHAIN_RPC",      "https://rpc.pulsechain.com")

REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE_FILE = os.path.join(REPO_ROOT, "scripts", "data", "layer_b_ammo.json")

# ─── Function selectors ──────────────────────────────────────────────────
SEL_BALANCE_OF   = Web3.keccak(text="balanceOf(address)")[:4]
SEL_ALLOWANCE    = Web3.keccak(text="allowance(address,address)")[:4]
SEL_APPROVE      = Web3.keccak(text="approve(address,uint256)")[:4]
SEL_DECIMALS     = Web3.keccak(text="decimals()")[:4]
SEL_DEBENTURE    = Web3.keccak(text="Debenture()")[:4]
SEL_PARENT       = Web3.keccak(text="Parent()")[:4]
SEL_TT_MINT      = Web3.keccak(text="mint(uint256)")[:4]
SEL_TT_CLAIM     = Web3.keccak(text="Claim(address,uint256)")[:4]
SEL_V2M_NEW      = Web3.keccak(text="New(string,string,uint256,address)")[:4]
SEL_V2M_TT       = Web3.keccak(text="TreasuryTokens(address)")[:4]

# ─── Web3 clients ────────────────────────────────────────────────────────
w3_read   = Web3(Web3.HTTPProvider(READ_RPC,   request_kwargs={"timeout": 30}))
w3_submit = Web3(Web3.HTTPProvider(SUBMIT_RPC, request_kwargs={"timeout": 60}))

# ─── ERC20 / TT reads ────────────────────────────────────────────────────
def erc20_balance(token: str, holder: str) -> int:
    data = SEL_BALANCE_OF + abi_encode(["address"], [holder])
    raw  = w3_read.eth.call({"to": token, "data": data})
    return abi_decode(["uint256"], raw)[0]

def erc20_allowance(token: str, owner: str, spender: str) -> int:
    data = SEL_ALLOWANCE + abi_encode(["address", "address"], [owner, spender])
    raw  = w3_read.eth.call({"to": token, "data": data})
    return abi_decode(["uint256"], raw)[0]

def tt_debenture(token: str) -> bool:
    raw = w3_read.eth.call({"to": token, "data": SEL_DEBENTURE})
    return abi_decode(["bool"], raw)[0]

def tt_parent(token: str) -> str:
    raw = w3_read.eth.call({"to": token, "data": SEL_PARENT})
    return Web3.to_checksum_address(abi_decode(["address"], raw)[0])

def v2m_treasury_owner(token: str) -> str:
    data = SEL_V2M_TT + abi_encode(["address"], [token])
    raw  = w3_read.eth.call({"to": V2MINTER, "data": data})
    return Web3.to_checksum_address(abi_decode(["address"], raw)[0])


# ─── State file I/O ──────────────────────────────────────────────────────
def _initial_state() -> dict:
    return {
        "deployed_at_block": None,
        "target": {"symbol": "PARADE", "address": PARADE, "parent": DFM},
        "probe_verified": False,
        "ammo": [],
    }

def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return _initial_state()
    with open(STATE_FILE) as f:
        return json.load(f)

def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


# ─── TX helpers ──────────────────────────────────────────────────────────
def _load_signing_key() -> str:
    pk = os.environ.get("JOEY_PK") or os.environ.get("DYSNOMIA_PRIVATE_KEY")
    if not pk:
        print("ERROR: set JOEY_PK or DYSNOMIA_PRIVATE_KEY env var", file=sys.stderr)
        sys.exit(2)
    return pk if pk.startswith("0x") else "0x" + pk


def build_gas_params() -> dict:
    base_fee = w3_read.eth.gas_price
    if base_fee > GAS_PRICE_CEIL:
        raise RuntimeError(f"gas too high: {base_fee/1e9:.0f} Beats > ceiling {GAS_PRICE_CEIL/1e9:.0f} Beats")
    max_fee = max(int(base_fee * 1.5), base_fee + PRIORITY_FEE + 1)
    return {"maxFeePerGas": max_fee, "maxPriorityFeePerGas": PRIORITY_FEE}


def simulate_call(to: str, data: bytes, value: int = 0, sender: str = JOEY) -> bytes:
    return w3_read.eth.call({"from": sender, "to": to, "data": data, "value": value})


def preflight_gas() -> None:
    pls = w3_read.eth.get_balance(JOEY)
    if pls < PLS_FLOOR:
        raise RuntimeError(f"PLS balance {pls/1e18:,.0f} below floor {PLS_FLOOR/1e18:,.0f}")
    gp = w3_read.eth.gas_price
    if gp > GAS_PRICE_CEIL:
        raise RuntimeError(f"gas too high: {gp/1e9:.0f} Beats")


def send_tx(to: str, data: bytes, value: int = 0, *, label: str, dry_run: bool) -> Optional[dict]:
    print(f"\n── {label} ──")

    try:
        simulate_call(to, data, value)
        print(f"  simulate: OK")
    except ContractLogicError as e:
        print(f"  simulate: REVERT — {e}")
        raise
    except Exception as e:
        print(f"  simulate: ERROR — {e}")
        raise

    try:
        est = w3_read.eth.estimate_gas({"from": JOEY, "to": to, "data": data, "value": value})
    except Exception as e:
        print(f"  estimate_gas: FAIL — {e}")
        raise
    gas_limit = int(est * GAS_MULT)
    print(f"  estimate_gas: {est:,} → gas_limit {gas_limit:,}")

    gas_params = build_gas_params()
    print(f"  maxFeePerGas: {gas_params['maxFeePerGas']/1e9:,.0f} Beats, priority: {gas_params['maxPriorityFeePerGas']/1e9:.6f} Beats")

    if dry_run:
        print("  [dry-run] skipping submit")
        return None

    nonce = w3_submit.eth.get_transaction_count(JOEY)
    tx = {
        "from":     JOEY,
        "to":       to,
        "data":     data,
        "value":    value,
        "gas":      gas_limit,
        "nonce":    nonce,
        "chainId":  CHAIN_ID,
        "type":     2,
        **gas_params,
    }
    signed = w3_submit.eth.account.sign_transaction(tx, _load_signing_key())
    tx_hash = w3_submit.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  submit: 0x{tx_hash.hex()}  (nonce {nonce})")

    receipt = None
    try:
        receipt = w3_submit.eth.wait_for_transaction_receipt(tx_hash, timeout=420)
    except Exception:
        for _ in range(60):
            try:
                receipt = w3_read.eth.get_transaction_receipt(tx_hash)
                break
            except Exception:
                time.sleep(5)
        if receipt is None:
            raise RuntimeError(f"TX 0x{tx_hash.hex()} not confirmed after 720s — check explorer")
    if receipt["status"] != 1:
        raise RuntimeError(f"TX 0x{tx_hash.hex()} reverted on-chain")
    print(f"  confirmed: block {receipt['blockNumber']}, gas used {receipt['gasUsed']:,}")
    return dict(receipt)


def confirm_or_abort(prompt: str, skip: bool) -> None:
    if skip:
        return
    ans = input(f"\n{prompt} [y/N]: ").strip().lower()
    if ans != "y":
        print("Aborted.")
        sys.exit(0)


# ─── Phase: approve ──────────────────────────────────────────────────────
def _encode_approve(spender: str, amount: int) -> bytes:
    return SEL_APPROVE + abi_encode(["address", "uint256"], [spender, amount])


def do_approve(*, dry_run: bool, skip_confirm: bool) -> None:
    """Static MAX approvals: WM→V2Minter (if not already set), DFM→PARADE."""
    preflight_gas()
    print(f"Phase: approve  dry_run={dry_run}")

    pairs = [
        ("WM → V2Minter", WM,  V2MINTER),
        ("DFM → PARADE",  DFM, PARADE),
    ]

    todo = []
    for label, token, spender in pairs:
        cur = erc20_allowance(token, JOEY, spender)
        if cur >= MAX_UINT256 >> 1:
            print(f"  {label}: already MAX — skip")
            continue
        todo.append((label, token, spender))

    if not todo:
        print("\nAll approvals already set. Nothing to do.")
        return

    print(f"\nPending approvals: {len(todo)}")
    for label, _, _ in todo:
        print(f"  - {label}")
    confirm_or_abort(f"Submit {len(todo)} approval TX(s)?", skip_confirm or dry_run)

    for label, token, spender in todo:
        data = _encode_approve(spender, MAX_UINT256)
        send_tx(token, data, label=f"approve {label}", dry_run=dry_run)

    print("\nApprove phase complete.")


# ─── Phase: deploy ───────────────────────────────────────────────────────
AMMO_PLAN = [
    ("幹 B01", "幹B01"),
    ("幹 B02", "幹B02"),
    ("幹 B03", "幹B03"),
    ("幹 B04", "幹B04"),
    ("幹 B05", "幹B05"),
]
AMMO_INITIAL_MINT = 1 * 10**18


def _encode_v2m_new(name: str, symbol: str, initial_mint: int, parent: str) -> bytes:
    return SEL_V2M_NEW + abi_encode(
        ["string", "string", "uint256", "address"],
        [name, symbol, initial_mint, parent],
    )


def _predict_ammo_address(name: str, symbol: str, initial_mint: int, parent: str) -> str:
    data = _encode_v2m_new(name, symbol, initial_mint, parent)
    raw  = simulate_call(V2MINTER, data)
    return Web3.to_checksum_address(abi_decode(["address"], raw)[0])


def do_deploy(*, dry_run: bool, skip_confirm: bool) -> None:
    """Deploy 5 幹B ammo (Parent=DFM) + interleaved DFM→ammo + ammo→PARADE approvals."""
    preflight_gas()
    state = load_state()
    already = {a["symbol"] for a in state.get("ammo", [])}
    print(f"Phase: deploy  dry_run={dry_run}  already_deployed={sorted(already)}")

    wm_bal = erc20_balance(WM, JOEY)
    needed_wm = AMMO_INITIAL_MINT * (5 - len(already))
    if wm_bal < needed_wm:
        raise RuntimeError(f"Insufficient WM: have {wm_bal/1e18:.4f}, need {needed_wm/1e18:.4f}")
    wm_allow = erc20_allowance(WM, JOEY, V2MINTER)
    if wm_allow < needed_wm:
        raise RuntimeError("WM→V2Minter allowance too low — run --phase approve first")

    pending = [(n, s) for n, s in AMMO_PLAN if s not in already]
    if not pending:
        print("\nAll 5 Layer B ammo already deployed.")
        return

    confirm_or_abort(
        f"Deploy {len(pending)} ammo tokens × (1 New + 2 approves) = {len(pending)*3} TXs?",
        skip_confirm or dry_run,
    )

    for name, symbol in pending:
        print(f"\n━━━ Deploying {symbol} ━━━")

        predicted = _predict_ammo_address(name, symbol, AMMO_INITIAL_MINT, DFM)
        print(f"  predicted address: {predicted}")

        new_data = _encode_v2m_new(name, symbol, AMMO_INITIAL_MINT, DFM)
        receipt = send_tx(V2MINTER, new_data, label=f"V2Minter.New({symbol}, parent=DFM)", dry_run=dry_run)

        if dry_run:
            entry = {
                "symbol":             symbol,
                "address":            predicted,
                "deploy_tx":          None,
                "debenture_verified": None,
                "parent":             DFM,
                "dry_run":            True,
            }
        else:
            # Read RPC may lag behind submit RPC for a few seconds. Poll both
            # before declaring failure — fall back to submit RPC if read RPC
            # still shows no code.
            code = b""
            for attempt in range(12):  # ~30s total
                code = w3_read.eth.get_code(predicted)
                if code not in (b"", b"0x", None):
                    break
                code = w3_submit.eth.get_code(predicted)
                if code not in (b"", b"0x", None):
                    break
                time.sleep(2.5)
            if code in (b"", b"0x", None):
                raise RuntimeError(f"{symbol}: no code at predicted address {predicted} after 30s on either RPC")
            if not tt_debenture(predicted):
                raise RuntimeError(f"{symbol} Debenture=False after deploy — aborting")
            if tt_parent(predicted) != DFM:
                raise RuntimeError(f"{symbol} Parent != DFM — aborting")
            if v2m_treasury_owner(predicted) != JOEY:
                raise RuntimeError(f"{symbol} V2Minter.TreasuryTokens[ammo] != Joey — aborting")
            print(f"  verified: Debenture=true, Parent=DFM, Owner=Joey")

            tx_hash = receipt["transactionHash"]
            entry = {
                "symbol":             symbol,
                "address":            predicted,
                "deploy_tx":          "0x" + tx_hash.hex() if isinstance(tx_hash, bytes) else tx_hash,
                "debenture_verified": True,
                "parent":             DFM,
            }

        # DFM → ammo approval
        send_tx(
            DFM,
            _encode_approve(predicted, MAX_UINT256),
            label=f"DFM → {symbol} approve MAX",
            dry_run=dry_run,
        )

        # ammo → PARADE approval
        send_tx(
            predicted,
            _encode_approve(PARADE, MAX_UINT256),
            label=f"{symbol} → PARADE approve MAX",
            dry_run=dry_run,
        )

        if not dry_run:
            state.setdefault("ammo", []).append(entry)
            if state.get("deployed_at_block") is None:
                state["deployed_at_block"] = w3_read.eth.block_number
            save_state(state)
            print(f"  state persisted: {STATE_FILE}")

    print("\nDeploy phase complete.")


# ─── Phase: probe ────────────────────────────────────────────────────────
def _encode_tt_mint(amount: int) -> bytes:
    return SEL_TT_MINT + abi_encode(["uint256"], [amount])


def _encode_tt_claim(spend_token: str, amount: int) -> bytes:
    return SEL_TT_CLAIM + abi_encode(["address", "uint256"], [spend_token, amount])


def do_probe(*, dry_run: bool, skip_confirm: bool) -> None:
    """1-unit sanity check: verify PARADE accepts our ammo for Claim.

    TX 1: PARADE.mint(1) — seeds PARADE's DFM vault with 1 DFM
    TX 2: PARADE.Claim(幹B01, 1) — uses 1 幹B01 from initial deploy mint,
          returns 1 DFM. If PARADE rejects our ammo (parent check / ownership
          check), this reverts and probe fails.

    On success, writes probe_verified=true to state.
    """
    preflight_gas()
    state = load_state()
    ammo = state.get("ammo", [])
    if len(ammo) < 1:
        raise RuntimeError("No ammo deployed. Run --phase deploy first.")

    target = state.get("target", {})
    if target.get("address", "").lower() != PARADE.lower():
        raise RuntimeError(f"State target mismatch — expected PARADE {PARADE}, got {target.get('address')}")

    # Static on-chain assertions before any TX
    print(f"Phase: probe  dry_run={dry_run}")
    print("\nStatic verification:")
    parade_parent = tt_parent(PARADE)
    print(f"  PARADE.Parent(): {parade_parent}  {'✓' if parade_parent == DFM else '✗ expected DFM'}")
    if parade_parent != DFM:
        raise RuntimeError(f"PARADE.Parent != DFM — aborting probe")

    first = ammo[0]
    ammo_addr = Web3.to_checksum_address(first["address"])
    ammo_sym  = first["symbol"]
    deb = tt_debenture(ammo_addr)
    par = tt_parent(ammo_addr)
    print(f"  {ammo_sym}.Debenture(): {deb}  {'✓' if deb else '✗ must be true'}")
    print(f"  {ammo_sym}.Parent(): {par}  {'✓' if par == DFM else '✗ expected DFM'}")
    if not deb:
        raise RuntimeError(f"{ammo_sym} Debenture=false — aborting probe")
    if par != DFM:
        raise RuntimeError(f"{ammo_sym} Parent != DFM — aborting probe")

    # Allowances
    if erc20_allowance(DFM, JOEY, PARADE) < 10**18:
        raise RuntimeError("DFM → PARADE allowance too low — run --phase approve")
    if erc20_allowance(ammo_addr, JOEY, PARADE) < 10**18:
        raise RuntimeError(f"{ammo_sym} → PARADE allowance too low — run --phase deploy")

    # Ammo inventory check
    ammo_bal = erc20_balance(ammo_addr, JOEY)
    if ammo_bal < 10**18:
        raise RuntimeError(f"Joey has {ammo_bal/1e18} {ammo_sym} — need at least 1 for probe")

    # DFM inventory check
    dfm_bal = erc20_balance(DFM, JOEY)
    if dfm_bal < 10**18:
        raise RuntimeError(f"Joey has {dfm_bal/1e18} DFM — need at least 1 for PARADE.mint(1)")

    confirm_or_abort(
        f"Run 2-TX probe? (PARADE.mint(1) + PARADE.Claim({ammo_sym}, 1) — consumes 1 {ammo_sym})",
        skip_confirm or dry_run,
    )

    # Pre-snapshot
    pre_parade = erc20_balance(PARADE, JOEY)
    pre_dfm    = erc20_balance(DFM,    JOEY)
    pre_ammo   = erc20_balance(ammo_addr, JOEY)

    # TX 1: PARADE.mint(1)
    send_tx(PARADE, _encode_tt_mint(10**18), label="PARADE.mint(1)", dry_run=dry_run)

    # TX 2: PARADE.Claim(幹B01, 1) — the critical test
    send_tx(
        PARADE,
        _encode_tt_claim(ammo_addr, 10**18),
        label=f"PARADE.Claim({ammo_sym}, 1)  [KEY TEST]",
        dry_run=dry_run,
    )

    if dry_run:
        print("\n[dry-run] probe TXs simulated OK — run without --dry-run to record probe_verified.")
        return

    time.sleep(2)
    post_parade = erc20_balance(PARADE, JOEY)
    post_dfm    = erc20_balance(DFM,    JOEY)
    post_ammo   = erc20_balance(ammo_addr, JOEY)

    d_parade = post_parade - pre_parade
    d_dfm    = post_dfm    - pre_dfm
    d_ammo   = post_ammo   - pre_ammo

    print(f"\nPost-probe deltas:")
    print(f"  ΔPARADE: {d_parade/1e18:+,.6f}   (expect +1)")
    print(f"  ΔDFM:    {d_dfm/1e18:+,.6f}      (expect 0: -1 mint + 1 claim)")
    print(f"  Δ{ammo_sym}: {d_ammo/1e18:+,.6f}  (expect -1)")

    if d_parade != 10**18:
        raise RuntimeError(f"PARADE delta wrong: {d_parade} vs +1e18")
    if d_dfm != 0:
        raise RuntimeError(f"DFM delta wrong: {d_dfm} vs 0 (mint -1 + claim +1 should cancel)")
    if d_ammo != -10**18:
        raise RuntimeError(f"{ammo_sym} delta wrong: {d_ammo} vs -1e18")

    state["probe_verified"] = True
    state["probe_block"]    = w3_read.eth.block_number
    save_state(state)
    print(f"\n✓ Probe successful. PARADE accepts our ammo.")
    print(f"  state.probe_verified = true  →  {STATE_FILE}")
    print("  You may now run --phase cycle.")


# ─── Phase: cycle ────────────────────────────────────────────────────────
def do_cycle(*, n: int, hold_back: int = 0, dry_run: bool, skip_confirm: bool) -> None:
    """One batch cycle: PARADE.mint(5N) + ammo.mint(N)×5 + PARADE.Claim(ammo, N-K)×5."""
    if n <= 0:
        raise ValueError("--n must be positive")
    if hold_back < 0:
        raise ValueError("--hold-back must be >= 0")
    if hold_back > n:
        raise ValueError(f"--hold-back ({hold_back}) cannot exceed --n ({n})")
    preflight_gas()

    state = load_state()
    ammo_entries = state.get("ammo", [])
    if len(ammo_entries) != 5:
        raise RuntimeError(f"state file has {len(ammo_entries)} ammo — need exactly 5. Run --phase deploy first.")
    if not state.get("probe_verified"):
        raise RuntimeError("Probe not verified. Run --phase probe first (or set probe_verified manually if you're sure).")

    ammo_addrs = [Web3.to_checksum_address(a["address"]) for a in ammo_entries]

    N_wei       = n * 10**18
    K_wei       = hold_back * 10**18
    CLAIM_WEI   = N_wei - K_wei
    claim_amt   = n - hold_back
    TOTAL       = 5 * N_wei
    skip_claim  = (hold_back == n)
    tx_count    = 1 + 5 + (0 if skip_claim else 5)
    print(f"Phase: cycle  N={n}  hold_back={hold_back}  claim={claim_amt}  tx_count={tx_count}  dry_run={dry_run}")

    # DFM balance check: 10N needed (5N for PARADE.mint + 5×N for ammo.mint)
    dfm_bal = erc20_balance(DFM, JOEY)
    if dfm_bal < 10 * N_wei:
        raise RuntimeError(f"DFM balance {dfm_bal/1e18:,.0f} < 10×N {10*n:,}")

    # Allowances
    if erc20_allowance(DFM, JOEY, PARADE) < TOTAL:
        raise RuntimeError("DFM → PARADE allowance too low — run --phase approve")
    for addr in ammo_addrs:
        if erc20_allowance(DFM, JOEY, addr) < N_wei:
            raise RuntimeError(f"DFM → {addr} allowance too low — run --phase deploy")
        if not skip_claim and erc20_allowance(addr, JOEY, PARADE) < CLAIM_WEI:
            raise RuntimeError(f"{addr} → PARADE allowance too low — run --phase deploy")

    # Debenture verification
    for entry in ammo_entries:
        addr = entry["address"]
        if not tt_debenture(addr):
            raise RuntimeError(f"{entry['symbol']} Debenture=False! Claim will revert. Aborting.")

    # Pre-snapshot
    pre = {
        "dfm_joey":    erc20_balance(DFM,    JOEY),
        "parade_joey": erc20_balance(PARADE, JOEY),
        "dfm_ammo":    [erc20_balance(DFM, a) for a in ammo_addrs],
        "joey_ammo":   [erc20_balance(a,   JOEY) for a in ammo_addrs],
    }
    print(f"\nPre-batch state:")
    print(f"  Joey DFM:    {pre['dfm_joey']/1e18:,.6f}")
    print(f"  Joey PARADE: {pre['parade_joey']/1e18:,.6f}")
    for i, bal in enumerate(pre["dfm_ammo"]):
        print(f"  {ammo_entries[i]['symbol']} DFM vault: {bal/1e18:,.6f}  |  Joey holds: {pre['joey_ammo'][i]/1e18:,.6f}")

    dfm_spend      = 5 * (n + hold_back)
    hold_back_note = "" if hold_back == 0 else f" + hold back {hold_back} of each ammo ({5*hold_back} total)"
    confirm_or_abort(
        f"Execute {tx_count}-TX batch? (spend {dfm_spend} DFM, gain {5*n} PARADE{hold_back_note})",
        skip_confirm or dry_run,
    )

    # TX 1: PARADE.mint(5N)
    send_tx(PARADE, _encode_tt_mint(TOTAL), label=f"PARADE.mint({5*n})", dry_run=dry_run)

    # TX 2-6: ammo.mint(N)
    for entry, addr in zip(ammo_entries, ammo_addrs):
        send_tx(addr, _encode_tt_mint(N_wei), label=f"{entry['symbol']}.mint({n})", dry_run=dry_run)

    # TX 7-11: PARADE.Claim(ammo, N-K)
    if skip_claim:
        print(f"\n[hold-back={n}] Skipping Claim phase — all {5*n} ammo retained in Joey's wallet.")
    else:
        for entry, addr in zip(ammo_entries, ammo_addrs):
            send_tx(
                PARADE,
                _encode_tt_claim(addr, CLAIM_WEI),
                label=f"PARADE.Claim({entry['symbol']}, {claim_amt})",
                dry_run=dry_run,
            )

    if dry_run:
        print(f"\n[dry-run] {tx_count} TXs simulated OK.")
        return

    # Post-snapshot + verification
    time.sleep(2)
    post = {
        "dfm_joey":    erc20_balance(DFM,    JOEY),
        "parade_joey": erc20_balance(PARADE, JOEY),
        "dfm_ammo":    [erc20_balance(DFM, a) for a in ammo_addrs],
        "joey_ammo":   [erc20_balance(a,   JOEY) for a in ammo_addrs],
    }
    d_dfm    = post["dfm_joey"]    - pre["dfm_joey"]
    d_parade = post["parade_joey"] - pre["parade_joey"]
    print(f"\nPost-batch state:")
    print(f"  Joey DFM:    {post['dfm_joey']/1e18:,.6f}  (Δ {d_dfm/1e18:+,.6f})")
    print(f"  Joey PARADE: {post['parade_joey']/1e18:,.6f}  (Δ {d_parade/1e18:+,.6f})")
    for i, (bal_now, bal_pre) in enumerate(zip(post["dfm_ammo"], pre["dfm_ammo"])):
        d    = bal_now - bal_pre
        held = post["joey_ammo"][i] - pre["joey_ammo"][i]
        print(f"  {ammo_entries[i]['symbol']} DFM vault: {bal_now/1e18:,.6f}  (Δ {d/1e18:+,.6f})  |  Joey {ammo_entries[i]['symbol']} Δ {held/1e18:+,.6f}")

    # Invariants:
    #   DFM:    -(5N + 5K)
    #   PARADE: +5N
    #   each ammo vault: +N
    #   Joey per-ammo: +K
    expected_dfm_delta    = -(5 * n + 5 * hold_back) * 10**18
    expected_parade_delta = +5 * N_wei
    if d_dfm != expected_dfm_delta:
        raise RuntimeError(f"DFM delta mismatch: got {d_dfm}, expected {expected_dfm_delta}")
    if d_parade != expected_parade_delta:
        raise RuntimeError(f"PARADE delta mismatch: got {d_parade}, expected {expected_parade_delta}")
    for i, (bal_now, bal_pre) in enumerate(zip(post["dfm_ammo"], pre["dfm_ammo"])):
        if bal_now - bal_pre != N_wei:
            raise RuntimeError(f"{ammo_entries[i]['symbol']} vault delta wrong: {bal_now-bal_pre} vs {N_wei}")
    for i, (bal_now, bal_pre) in enumerate(zip(post["joey_ammo"], pre["joey_ammo"])):
        held = bal_now - bal_pre
        if held != K_wei:
            raise RuntimeError(f"{ammo_entries[i]['symbol']} Joey-holdings delta wrong: {held} vs {K_wei}")

    print("\n✓ Cycle phase complete — all invariants hold.")


# ─── --verify mode ───────────────────────────────────────────────────────
def do_verify() -> None:
    block = w3_read.eth.block_number
    print(f"Block: {block}")
    print(f"\n=== Joey Wallet ({JOEY}) ===")
    print(f"  PLS:    {w3_read.eth.get_balance(JOEY)/1e18:>22,.4f}")
    print(f"  DFM:    {erc20_balance(DFM,    JOEY)/1e18:>22,.6f}")
    print(f"  PARADE: {erc20_balance(PARADE, JOEY)/1e18:>22,.6f}")
    print(f"  WM:     {erc20_balance(WM,     JOEY)/1e18:>22,.6f}")
    print(f"  Nonce: {w3_read.eth.get_transaction_count(JOEY)}")

    print(f"\n=== Allowances (MAX = {MAX_UINT256}) ===")
    wm_to_v2m     = erc20_allowance(WM,  JOEY, V2MINTER)
    dfm_to_parade = erc20_allowance(DFM, JOEY, PARADE)
    print(f"  WM  → V2Minter: {'MAX' if wm_to_v2m     >= MAX_UINT256 >> 1 else 'NOT SET'}")
    print(f"  DFM → PARADE:   {'MAX' if dfm_to_parade >= MAX_UINT256 >> 1 else 'NOT SET'}")

    print(f"\n=== PARADE on-chain ===")
    print(f"  Parent:    {tt_parent(PARADE)}  {'✓ DFM' if tt_parent(PARADE) == DFM else '✗'}")
    print(f"  Debenture: {tt_debenture(PARADE)} (not required for target)")
    print(f"  totalSupply: (not shown — large)")

    state = load_state()
    print(f"\n=== Layer B state ({STATE_FILE}) ===")
    print(f"  probe_verified: {state.get('probe_verified')}")
    if not state.get("ammo"):
        print("  (no ammo deployed)")
    else:
        for ammo in state["ammo"]:
            addr = ammo["address"]
            bal_dfm_vault = erc20_balance(DFM, addr)
            bal_joey      = erc20_balance(addr, JOEY)
            dfm_to_a      = erc20_allowance(DFM, JOEY, addr)
            a_to_parade   = erc20_allowance(addr, JOEY, PARADE)
            deb_now       = tt_debenture(addr)
            print(f"  {ammo['symbol']:>6} @ {addr}")
            print(f"    DFM locked:      {bal_dfm_vault/1e18:,.6f}")
            print(f"    Joey holds:      {bal_joey/1e18:,.6f}")
            print(f"    Debenture:       {deb_now}")
            print(f"    DFM → ammo:      {'MAX' if dfm_to_a    >= MAX_UINT256 >> 1 else 'NOT SET'}")
            print(f"    ammo → PARADE:   {'MAX' if a_to_parade >= MAX_UINT256 >> 1 else 'NOT SET'}")


# ─── CLI ─────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="DFM → PARADE treasury cycle (Layer B)")
    parser.add_argument("--phase", choices=["approve", "deploy", "probe", "cycle"], help="phase to execute")
    parser.add_argument("--n", type=int, default=10, help="tokens per round (cycle phase)")
    parser.add_argument("--hold-back", type=int, default=0, help="retain this many of each ammo during Claim (default 0)")
    parser.add_argument("--dry-run", action="store_true", help="simulate only, do not submit")
    parser.add_argument("--yes",     action="store_true", help="skip per-phase confirmation")
    parser.add_argument("--verify",  action="store_true", help="print state and exit")
    args = parser.parse_args()

    if args.verify:
        do_verify()
        return 0

    if not args.phase:
        parser.error("--phase is required unless using --verify")

    if args.phase == "approve":
        do_approve(dry_run=args.dry_run, skip_confirm=args.yes)
    elif args.phase == "deploy":
        do_deploy(dry_run=args.dry_run, skip_confirm=args.yes)
    elif args.phase == "probe":
        do_probe(dry_run=args.dry_run, skip_confirm=args.yes)
    elif args.phase == "cycle":
        do_cycle(n=args.n, hold_back=args.hold_back, dry_run=args.dry_run, skip_confirm=args.yes)

    return 0


if __name__ == "__main__":
    sys.exit(main())
