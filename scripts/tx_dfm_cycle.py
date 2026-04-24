#!/usr/bin/env python3
"""
tx_dfm_cycle.py — FDIC → DFM Treasury Cycle

Phases:
  --phase approve    Static MAX approvals (WM→V2Minter, FDIC→DFM)
  --phase deploy     Deploy 5 ammo tokens + FDIC→ammo + ammo→DFM approvals
  --phase cycle      Execute one 11-TX batch (DFM.mint + 5×ammo.mint + 5×DFM.Claim)

Flags:
  --n <int>          Tokens per round for cycle phase (default 10)
  --dry-run          eth_call simulate every TX, submit nothing
  --yes              Skip per-phase interactive confirmation
  --verify           Print balances + ammo state + allowances, exit

Spec: docs/superpowers/specs/2026-04-24-fdic-dfm-cycle-design.md
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
FDIC     = Web3.to_checksum_address("0x812571A12330A74E2A3C1fF8953f6f3aac7a83e9")
DFM      = Web3.to_checksum_address("0x51160F352ED148C89d48dfe6384Edd07aFA24E0E")
FED      = Web3.to_checksum_address("0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff")
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
STATE_FILE = os.path.join(REPO_ROOT, "scripts", "data", "dfm_cycle_ammo.json")

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

# ─── ERC20 / TT reads (via raw eth_call to avoid contract-object overhead) ───
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
def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"deployed_at_block": None, "ammo": []}
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
    """Raw eth_call simulation. Raises ContractLogicError on revert with decoded message if available."""
    return w3_read.eth.call({"from": sender, "to": to, "data": data, "value": value})


def preflight_gas() -> None:
    """Abort if gas price is over ceiling or PLS balance below floor."""
    pls = w3_read.eth.get_balance(JOEY)
    if pls < PLS_FLOOR:
        raise RuntimeError(f"PLS balance {pls/1e18:,.0f} below floor {PLS_FLOOR/1e18:,.0f}")
    gp = w3_read.eth.gas_price
    if gp > GAS_PRICE_CEIL:
        raise RuntimeError(f"gas too high: {gp/1e9:.0f} Beats")


def send_tx(to: str, data: bytes, value: int = 0, *, label: str, dry_run: bool) -> Optional[dict]:
    """
    Simulate via eth_call, estimate gas, then (unless dry_run) sign + submit + await receipt.
    Returns receipt dict on success, None on dry_run success. Raises on any failure.
    """
    print(f"\n── {label} ──")

    # 1. Simulate
    try:
        simulate_call(to, data, value)
        print(f"  simulate: OK")
    except ContractLogicError as e:
        print(f"  simulate: REVERT — {e}")
        raise
    except Exception as e:
        print(f"  simulate: ERROR — {e}")
        raise

    # 2. Gas estimate (with 2.5x multiplier)
    try:
        est = w3_read.eth.estimate_gas({"from": JOEY, "to": to, "data": data, "value": value})
    except Exception as e:
        print(f"  estimate_gas: FAIL — {e}")
        raise
    gas_limit = int(est * GAS_MULT)
    print(f"  estimate_gas: {est:,} → gas_limit {gas_limit:,}")

    # 3. Gas params
    gas_params = build_gas_params()
    print(f"  maxFeePerGas: {gas_params['maxFeePerGas']/1e9:,.0f} Beats, priority: {gas_params['maxPriorityFeePerGas']/1e9:.6f} Beats")

    if dry_run:
        print("  [dry-run] skipping submit")
        return None

    # 4. Sign + submit
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

    # 5. Await receipt — PulseChain inclusion latency can exceed 3 minutes; long timeout + read-RPC fallback
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
    """Static MAX approvals: WM→V2Minter, FDIC→DFM."""
    preflight_gas()
    print(f"Phase: approve  dry_run={dry_run}")

    pairs = [
        ("WM → V2Minter",  WM,   V2MINTER),
        ("FDIC → DFM",     FDIC, DFM),
    ]

    todo = []
    for label, token, spender in pairs:
        cur = erc20_allowance(token, JOEY, spender)
        if cur >= MAX_UINT256 >> 1:
            print(f"  {label}: already MAX ({cur}) — skip")
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
    ("幹 A01", "幹A01"),
    ("幹 A02", "幹A02"),
    ("幹 A03", "幹A03"),
    ("幹 A04", "幹A04"),
    ("幹 A05", "幹A05"),
]
AMMO_INITIAL_MINT = 1 * 10**18  # 1 token × 10^18 — matches user spec


def _encode_v2m_new(name: str, symbol: str, initial_mint: int, parent: str) -> bytes:
    return SEL_V2M_NEW + abi_encode(
        ["string", "string", "uint256", "address"],
        [name, symbol, initial_mint, parent],
    )


def _predict_ammo_address(name: str, symbol: str, initial_mint: int, parent: str) -> str:
    """eth_call V2Minter.New(...) returns the new contract address without submitting."""
    data = _encode_v2m_new(name, symbol, initial_mint, parent)
    raw  = simulate_call(V2MINTER, data)
    return Web3.to_checksum_address(abi_decode(["address"], raw)[0])


def do_deploy(*, dry_run: bool, skip_confirm: bool) -> None:
    """Deploy 5 ammo tokens + interleaved FDIC→ammo + ammo→DFM approvals."""
    preflight_gas()
    state = load_state()
    already = {a["symbol"] for a in state.get("ammo", [])}
    print(f"Phase: deploy  dry_run={dry_run}  already_deployed={sorted(already)}")

    # Verify prerequisites
    wm_bal = erc20_balance(WM, JOEY)
    needed_wm = AMMO_INITIAL_MINT * (5 - len(already))
    if wm_bal < needed_wm:
        raise RuntimeError(f"Insufficient WM: have {wm_bal/1e18:.4f}, need {needed_wm/1e18:.4f}")
    wm_allow = erc20_allowance(WM, JOEY, V2MINTER)
    if wm_allow < needed_wm:
        raise RuntimeError("WM→V2Minter allowance too low — run --phase approve first")

    pending = [(n, s) for n, s in AMMO_PLAN if s not in already]
    if not pending:
        print("\nAll 5 ammo already deployed.")
        return

    confirm_or_abort(
        f"Deploy {len(pending)} ammo tokens × (1 New + 2 approves) = {len(pending)*3} TXs?",
        skip_confirm or dry_run,
    )

    for name, symbol in pending:
        print(f"\n━━━ Deploying {symbol} ━━━")

        predicted = _predict_ammo_address(name, symbol, AMMO_INITIAL_MINT, FDIC)
        print(f"  predicted address: {predicted}")

        new_data = _encode_v2m_new(name, symbol, AMMO_INITIAL_MINT, FDIC)
        receipt = send_tx(V2MINTER, new_data, label=f"V2Minter.New({symbol})", dry_run=dry_run)

        if dry_run:
            entry = {
                "symbol":             symbol,
                "address":            predicted,
                "deploy_tx":          None,
                "debenture_verified": None,
                "parent":             FDIC,
                "dry_run":            True,
            }
        else:
            # Verify on-chain state at predicted address
            code = w3_read.eth.get_code(predicted)
            if code in (b"", b"0x", None):
                raise RuntimeError(f"{symbol}: no code at predicted address {predicted}")
            if not tt_debenture(predicted):
                raise RuntimeError(f"{symbol} Debenture=False after deploy — aborting")
            if tt_parent(predicted) != FDIC:
                raise RuntimeError(f"{symbol} Parent != FDIC — aborting")
            if v2m_treasury_owner(predicted) != JOEY:
                raise RuntimeError(f"{symbol} V2Minter.TreasuryTokens[ammo] != Joey — aborting")
            print(f"  verified: Debenture=true, Parent=FDIC, Owner=Joey")

            entry = {
                "symbol":             symbol,
                "address":            predicted,
                "deploy_tx":          "0x" + receipt["transactionHash"].hex() if isinstance(receipt["transactionHash"], bytes) else receipt["transactionHash"],
                "debenture_verified": True,
                "parent":             FDIC,
            }

        # FDIC → ammo approval
        send_tx(
            FDIC,
            _encode_approve(predicted, MAX_UINT256),
            label=f"FDIC → {symbol} approve MAX",
            dry_run=dry_run,
        )

        # ammo → DFM approval
        send_tx(
            predicted,
            _encode_approve(DFM, MAX_UINT256),
            label=f"{symbol} → DFM approve MAX",
            dry_run=dry_run,
        )

        if not dry_run:
            state.setdefault("ammo", []).append(entry)
            if state.get("deployed_at_block") is None:
                state["deployed_at_block"] = w3_read.eth.block_number
            save_state(state)
            print(f"  state persisted: {STATE_FILE}")

    print("\nDeploy phase complete.")


# ─── Phase: cycle ────────────────────────────────────────────────────────
def _encode_tt_mint(amount: int) -> bytes:
    return SEL_TT_MINT + abi_encode(["uint256"], [amount])


def _encode_tt_claim(spend_token: str, amount: int) -> bytes:
    return SEL_TT_CLAIM + abi_encode(["address", "uint256"], [spend_token, amount])


def do_cycle(*, n: int, dry_run: bool, skip_confirm: bool) -> None:
    """One batch cycle: DFM.mint(5N) + ammo.mint(N)×5 + DFM.Claim(ammo, N)×5."""
    if n <= 0:
        raise ValueError("--n must be positive")
    preflight_gas()

    state = load_state()
    ammo_entries = state.get("ammo", [])
    if len(ammo_entries) != 5:
        raise RuntimeError(f"state file has {len(ammo_entries)} ammo — need exactly 5. Run --phase deploy first.")

    ammo_addrs = [Web3.to_checksum_address(a["address"]) for a in ammo_entries]

    # Scale to wei
    N_wei   = n * 10**18
    TOTAL   = 5 * N_wei
    print(f"Phase: cycle  N={n}  total_fdic_approvals_needed={10*n}  dry_run={dry_run}")

    # Prerequisite: FDIC balance for 10N (5N for DFM.mint + 5×N for ammo.mint)
    fdic_bal = erc20_balance(FDIC, JOEY)
    if fdic_bal < 10 * N_wei:
        raise RuntimeError(f"FDIC balance {fdic_bal/1e18:,.0f} < 10×N {10*n:,}")

    # Allowance checks
    if erc20_allowance(FDIC, JOEY, DFM) < TOTAL:
        raise RuntimeError("FDIC → DFM allowance too low — run --phase approve")
    for addr in ammo_addrs:
        if erc20_allowance(FDIC, JOEY, addr) < N_wei:
            raise RuntimeError(f"FDIC → {addr} allowance too low — run --phase deploy")
        if erc20_allowance(addr, JOEY, DFM) < N_wei:
            raise RuntimeError(f"{addr} → DFM allowance too low — run --phase deploy")

    # Live Debenture verification
    for entry in ammo_entries:
        addr = entry["address"]
        if not tt_debenture(addr):
            raise RuntimeError(f"{entry['symbol']} Debenture=False! Claim will revert. Aborting.")

    # Pre-snapshot
    pre = {
        "fdic_joey":  erc20_balance(FDIC, JOEY),
        "dfm_joey":   erc20_balance(DFM,  JOEY),
        "fdic_ammo":  [erc20_balance(FDIC, a) for a in ammo_addrs],
    }
    print(f"\nPre-batch state:")
    print(f"  Joey FDIC: {pre['fdic_joey']/1e18:,.6f}")
    print(f"  Joey DFM:  {pre['dfm_joey']/1e18:,.6f}")
    for i, bal in enumerate(pre["fdic_ammo"]):
        print(f"  {ammo_entries[i]['symbol']} FDIC vault: {bal/1e18:,.6f}")

    confirm_or_abort(
        f"Execute 11-TX batch? (will lock 5×{n} = {5*n} FDIC permanently, gain {5*n} DFM)",
        skip_confirm or dry_run,
    )

    # TX 1: DFM.mint(5N) — seeds DFM's FDIC vault and mints 5N DFM to Joey
    send_tx(DFM, _encode_tt_mint(TOTAL), label=f"DFM.mint({5*n})", dry_run=dry_run)

    # TXs 2-6: each ammo.mint(N)
    for entry, addr in zip(ammo_entries, ammo_addrs):
        send_tx(addr, _encode_tt_mint(N_wei), label=f"{entry['symbol']}.mint({n})", dry_run=dry_run)

    # TXs 7-11: each DFM.Claim(ammo, N)
    for entry, addr in zip(ammo_entries, ammo_addrs):
        send_tx(
            DFM,
            _encode_tt_claim(addr, N_wei),
            label=f"DFM.Claim({entry['symbol']}, {n})",
            dry_run=dry_run,
        )

    if dry_run:
        print("\n[dry-run] 11 TXs simulated OK.")
        return

    # Post-snapshot + verification
    time.sleep(2)  # small settle for RPC consistency
    post = {
        "fdic_joey":  erc20_balance(FDIC, JOEY),
        "dfm_joey":   erc20_balance(DFM,  JOEY),
        "fdic_ammo":  [erc20_balance(FDIC, a) for a in ammo_addrs],
    }
    d_fdic = post["fdic_joey"] - pre["fdic_joey"]
    d_dfm  = post["dfm_joey"]  - pre["dfm_joey"]
    print(f"\nPost-batch state:")
    print(f"  Joey FDIC: {post['fdic_joey']/1e18:,.6f}  (Δ {d_fdic/1e18:+,.6f})")
    print(f"  Joey DFM:  {post['dfm_joey']/1e18:,.6f}  (Δ {d_dfm/1e18:+,.6f})")
    for i, (bal_now, bal_pre) in enumerate(zip(post["fdic_ammo"], pre["fdic_ammo"])):
        d = bal_now - bal_pre
        print(f"  {ammo_entries[i]['symbol']} FDIC vault: {bal_now/1e18:,.6f}  (Δ {d/1e18:+,.6f})")

    # Hard assertions
    expected_fdic_delta = -5 * N_wei
    expected_dfm_delta  = +5 * N_wei
    if d_fdic != expected_fdic_delta:
        raise RuntimeError(f"FDIC delta mismatch: got {d_fdic}, expected {expected_fdic_delta}")
    if d_dfm != expected_dfm_delta:
        raise RuntimeError(f"DFM delta mismatch: got {d_dfm}, expected {expected_dfm_delta}")
    for i, (bal_now, bal_pre) in enumerate(zip(post["fdic_ammo"], pre["fdic_ammo"])):
        if bal_now - bal_pre != N_wei:
            raise RuntimeError(f"{ammo_entries[i]['symbol']} vault delta wrong: {bal_now-bal_pre} vs {N_wei}")

    print("\n✓ Cycle phase complete — all invariants hold.")


# ─── --verify mode ───────────────────────────────────────────────────────
def do_verify() -> None:
    block = w3_read.eth.block_number
    print(f"Block: {block}")
    print(f"\n=== Joey Wallet ({JOEY}) ===")
    print(f"  PLS:  {w3_read.eth.get_balance(JOEY)/1e18:>22,.4f}")
    print(f"  FDIC: {erc20_balance(FDIC, JOEY)/1e18:>22,.6f}")
    print(f"  FED:  {erc20_balance(FED,  JOEY)/1e18:>22,.6f}")
    print(f"  WM:   {erc20_balance(WM,   JOEY)/1e18:>22,.6f}")
    print(f"  DFM:  {erc20_balance(DFM,  JOEY)/1e18:>22,.6f}")
    print(f"  Nonce: {w3_read.eth.get_transaction_count(JOEY)}")

    print(f"\n=== Allowances (MAX = {MAX_UINT256}) ===")
    wm_to_v2m   = erc20_allowance(WM,   JOEY, V2MINTER)
    fdic_to_dfm = erc20_allowance(FDIC, JOEY, DFM)
    print(f"  WM   → V2Minter: {wm_to_v2m}  {'(MAX)' if wm_to_v2m >= MAX_UINT256 >> 1 else '(NOT SET)'}")
    print(f"  FDIC → DFM:      {fdic_to_dfm}  {'(MAX)' if fdic_to_dfm >= MAX_UINT256 >> 1 else '(NOT SET)'}")

    state = load_state()
    print(f"\n=== Ammo state ({STATE_FILE}) ===")
    if not state.get("ammo"):
        print("  (none deployed)")
    else:
        for ammo in state["ammo"]:
            addr = ammo["address"]
            bal_fdic    = erc20_balance(FDIC, addr)
            fdic_to_a   = erc20_allowance(FDIC, JOEY, addr)
            a_to_dfm    = erc20_allowance(addr, JOEY, DFM)
            deb_now     = tt_debenture(addr)
            print(f"  {ammo['symbol']:>6} @ {addr}")
            print(f"    FDIC locked:     {bal_fdic/1e18:,.6f}")
            print(f"    Debenture:       {deb_now}")
            print(f"    FDIC → ammo:     {'(MAX)' if fdic_to_a >= MAX_UINT256 >> 1 else '(NOT SET)'}")
            print(f"    ammo → DFM:      {'(MAX)' if a_to_dfm >= MAX_UINT256 >> 1 else '(NOT SET)'}")


# ─── CLI ─────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="FDIC → DFM treasury cycle")
    parser.add_argument("--phase", choices=["approve", "deploy", "cycle"], help="phase to execute")
    parser.add_argument("--n", type=int, default=10, help="tokens per round (cycle phase)")
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
    elif args.phase == "cycle":
        do_cycle(n=args.n, dry_run=args.dry_run, skip_confirm=args.yes)

    return 0


if __name__ == "__main__":
    sys.exit(main())
