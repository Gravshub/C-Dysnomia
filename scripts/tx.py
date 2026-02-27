#!/usr/bin/env python3
"""
tx.py — Standalone PulseChain transaction sender using web3.py

Why this exists:
  Nethereum's SendTransactionAsync (5-arg form) hangs on PulseChain.
  web3.py works reliably. This script is the authoritative TX sender
  for the Dysnomia client stack until C# TX sending is fixed.

Usage:
  python3 scripts/tx.py CONTRACT FUNCTION [ARG1 ARG2 ...]

  CONTRACT  — alias name (VOID, GIBS, etc.) OR raw 0x address
  FUNCTION  — Solidity function name (e.g. "Chat", "Username")
  ARGn      — function arguments as strings (auto-typed by ABI)

Environment:
  DYSNOMIA_PRIVATE_KEY  — sender private key (required)
  DYSNOMIA_RPC          — RPC endpoint (default: https://rpc.pulsechain.com)
  DYSNOMIA_REPO         — repo root for ABI lookup (default: script dir/..)

Examples:
  python3 scripts/tx.py VOID Chat "hello world"
  python3 scripts/tx.py GIBS Username "Joey"
  python3 scripts/tx.py 0x965B0d... Chat "test"

ABI resolution:
  1. Looks for compiled JSON in <repo>/solidity/out/ or <repo>/Wallet/bin/Contracts/
  2. Falls back to a minimal generic ABI for single-string-arg functions
  3. For view functions (constant=True), prints the result and exits 0
"""

import os, sys, json, glob, time
from pathlib import Path
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# ── Config ────────────────────────────────────────────────────────────────────

RPC     = os.environ.get("DYSNOMIA_RPC", "https://rpc.pulsechain.com")
PKEY    = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
REPO    = Path(os.environ.get("DYSNOMIA_REPO", Path(__file__).parent.parent))
CHAIN   = 369  # PulseChain mainnet

# Known aliases (kept in sync with LiveContracts.cs)
ALIASES = {
    "AFFECTION":         "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D",
    "CROWS":             "0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1",
    "WM":                "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29",
    "ATROPA":            "0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6",
    "VOID":              "0x965B0d74591bF30327075A247C47dBf487dCff08",
    "LAUFACTORY":        "0x965B0d74591bF30327075A247C47dBf487dCff08",
    "GIBS":              "0x66a08aa12da955eb63d7ac121a88b2b210a07b03",
    "DSS":               "0x91Df693177eE5C81016d0B7c4c2052A7d229c031",
    "DYSNOMIASELFSNI":   "0x91Df693177eE5C81016d0B7c4c2052A7d229c031",  # prefix match
}

# ── ABI helpers ───────────────────────────────────────────────────────────────

def resolve_alias(name: str) -> str:
    """Resolve alias name to 0x address, or pass through if already address."""
    if name.startswith("0x") and len(name) == 42:
        return Web3.to_checksum_address(name)
    upper = name.upper()
    for k, v in ALIASES.items():
        if upper == k or k.startswith(upper):
            return Web3.to_checksum_address(v)
    raise ValueError(f"Unknown alias: {name!r}  (use 0x address or add to ALIASES)")


def find_abi_for_file(sol_filename: str):
    """
    Search compiled JSON files for an ABI matching sol_filename.
    Handles solc --combined-json output format:
      { "contracts": { "/path/file.sol:ContractName": { "abi": [...], "bin": "..." } } }
    """
    search_dirs = [
        REPO / "Wallet" / "bin" / "Contracts",
        REPO / "solidity" / "out",
        REPO / "out",
    ]
    for d in search_dirs:
        for jf in sorted(d.glob("*.json")) if d.exists() else []:
            try:
                data = json.loads(jf.read_text())
                contracts = data.get("contracts", {})
                for key, val in contracts.items():
                    if sol_filename.lower() in key.lower():
                        abi = val.get("abi")
                        if isinstance(abi, str):
                            abi = json.loads(abi)
                        return abi
            except Exception:
                continue
    return None


def find_function_in_abi(abi, func_name: str):
    """Find a function entry in the ABI by name (case-insensitive prefix)."""
    for entry in abi:
        if entry.get("type") == "function":
            if entry["name"].lower() == func_name.lower():
                return entry
            if entry["name"].lower().startswith(func_name.lower()):
                return entry
    return None


def coerce_arg(value: str, solidity_type: str):
    """Cast a string CLI argument to the appropriate Python type for the ABI."""
    t = solidity_type.lower()
    if t == "bool":
        return value.lower() in ("true", "1", "yes")
    if t.startswith("uint") or t.startswith("int"):
        return int(value)
    if t == "address":
        if value.startswith("0x") and len(value) == 42:
            return Web3.to_checksum_address(value)
        return Web3.to_checksum_address(resolve_alias(value))
    if t.startswith("bytes"):
        return bytes.fromhex(value[2:]) if value.startswith("0x") else value.encode()
    return value  # string, etc.


# ── TX sender ─────────────────────────────────────────────────────────────────

def send_tx(w3: Web3, account, contract_addr: str, func_abi: dict, raw_args: list):
    """Build, sign, and send a transaction. Waits for receipt."""
    input_params = func_abi.get("inputs", [])
    if len(raw_args) != len(input_params):
        print(f"[tx] Arg count mismatch: ABI expects {len(input_params)}, got {len(raw_args)}", file=sys.stderr)
        if input_params:
            print(f"[tx] Expected: {[p['type'] + ' ' + p['name'] for p in input_params]}", file=sys.stderr)
        sys.exit(1)

    typed_args = [coerce_arg(v, input_params[i]["type"]) for i, v in enumerate(raw_args)]

    # Build minimal ABI for this single function so web3 can encode args
    mini_abi = [func_abi]
    contract = w3.eth.contract(address=contract_addr, abi=mini_abi)
    fn       = contract.functions[func_abi["name"]]

    # View / pure — just call, don't send TX
    if func_abi.get("stateMutability") in ("view", "pure") or func_abi.get("constant"):
        result = fn(*typed_args).call()
        print(f"[tx] {func_abi['name']}({', '.join(str(a) for a in typed_args)}) → {result}")
        return result

    # State-changing — estimate gas + send
    nonce   = w3.eth.get_transaction_count(account.address)
    gas_est = 500_000
    try:
        gas_est = int(fn(*typed_args).estimate_gas({"from": account.address}) * 1.15)
    except Exception as e:
        print(f"[tx] gas estimate failed ({e}), using {gas_est}", file=sys.stderr)

    tx = fn(*typed_args).build_transaction({
        "from":     account.address,
        "nonce":    nonce,
        "gas":      gas_est,
        "chainId":  CHAIN,
    })
    signed = account.sign_transaction(tx)
    txhash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"[tx] Sent: {txhash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(txhash, timeout=180)
    status  = "✓ Success" if receipt.status == 1 else "✗ Reverted"
    print(f"[tx] {status} (block {receipt.blockNumber}, gas {receipt.gasUsed})")
    return receipt


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(0)

    if not PKEY:
        print("[tx] Error: DYSNOMIA_PRIVATE_KEY not set", file=sys.stderr)
        sys.exit(1)

    contract_arg  = sys.argv[1]
    function_name = sys.argv[2]
    raw_args      = sys.argv[3:]

    # Connect
    w3 = Web3(Web3.HTTPProvider(RPC))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not w3.is_connected():
        print(f"[tx] Cannot connect to RPC: {RPC}", file=sys.stderr)
        sys.exit(1)
    print(f"[tx] Connected: block {w3.eth.block_number}")

    account = w3.eth.account.from_key(PKEY)
    print(f"[tx] Wallet: {account.address}")

    contract_addr = resolve_alias(contract_arg)
    print(f"[tx] Contract: {contract_addr}")

    # Try to find the ABI; fall back to minimal single-string-arg ABI
    # ABI search: try common sol filenames based on alias
    alias_to_sol = {
        "VOID":      "dysnomia/10_void.sol",
        "GIBS":      "dysnomia/11_lau.sol",
        "LAUFACTORY":"dysnomia/11c_laufactory.sol",
        "AFFECTION": "dysnomia/01_dysnomia.sol",
        "CROWS":     "dysnomia/01_dysnomia.sol",
        "WM":        "dysnomia/01_dysnomia.sol",
        "ATROPA":    "dysnomia/01_dysnomia.sol",
        "DSS":       "dysnomia/etc/DysnomiaSelfSnipev4.sol",
    }
    sol_hint = alias_to_sol.get(contract_arg.upper(), "")
    abi = find_abi_for_file(sol_hint) if sol_hint else None

    func_entry = None
    if abi:
        func_entry = find_function_in_abi(abi, function_name)
        if func_entry:
            print(f"[tx] ABI loaded, function: {func_entry['name']}")

    if func_entry is None:
        # Minimal fallback ABI — assumes single string argument (covers Chat, Username, Log)
        print(f"[tx] No ABI found for {function_name!r}, using minimal string-arg ABI", file=sys.stderr)
        func_entry = {
            "name":            function_name,
            "type":            "function",
            "stateMutability": "nonpayable",
            "inputs":  [{"name": "arg0", "type": "string"}] if raw_args else [],
            "outputs": [],
        }

    send_tx(w3, account, contract_addr, func_entry, raw_args)


if __name__ == "__main__":
    main()
