#!/usr/bin/env python3
"""
treasury_recon.py — Deep scan of Atropa Treasury Token ecosystem.

Loads the spine tracker dataset (1,254 V3/V4 tokens) + known V2 Federal tokens,
then reads on-chain state for each to find:
  1. Debenture status (True = unpublished = claimable = spine runner target)
  2. Self-balance (backing tokens held inside the contract)
  3. Parent balance (parent tokens held inside child treasury)
  4. DEX pair existence + reserves (V1 and V2)
  5. Cross-DEX arbitrage spreads
  6. Mint-claim loop candidates

Outputs:
  data/recon_results.json      — full scan results
  data/spine_opportunities.json — ranked profit opportunities
  data/v2_federal_tokens.json  — updated with live Debenture status
  data/token_master.json       — updated with on-chain data

Usage:
  python3 treasury_recon.py                     # scan all known tokens
  python3 treasury_recon.py --v2-only           # scan V2 Federal tokens only (fast)
  python3 treasury_recon.py --top 20            # show top 20 opportunities
  python3 treasury_recon.py --data-dir ./data   # custom data directory

Reads from:
  data/token_master.json       — merged token registry
  data/v2_federal_tokens.json  — V2 Federal candidates
  data/spine_map.json          — spine chain structures

Writes to:
  data/recon_results.json      — enriched scan results
  data/spine_opportunities.json — ranked opportunities for engines 5/6
"""

import json
import sys
import os
import time
import tempfile
import argparse
from collections import defaultdict
from web3 import Web3

# ─── RPC ────────────────────────────────────────────────────────────────────
RPC_READ = os.getenv("RPC_URL_READ", "https://rpc-pulsechain.g4mm4.io")
w3 = Web3(Web3.HTTPProvider(RPC_READ, request_kwargs={"timeout": 30}))

# ─── ABIs (minimal) ────────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs": [], "name": "name", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSupply", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "a", "type": "address"}], "name": "balanceOf",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

TREASURY_EXTRA_ABI = [
    {"inputs": [], "name": "Parent", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "Debenture", "outputs": [{"type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "_mintingKey", "outputs": [{"type": "uint64"}], "stateMutability": "view", "type": "function"},
]

FACTORY_ABI = [
    {"inputs": [{"name": "a", "type": "address"}, {"name": "b", "type": "address"}],
     "name": "getPair", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

PAIR_ABI = [
    {"inputs": [], "name": "getReserves",
     "outputs": [{"type": "uint112"}, {"type": "uint112"}, {"type": "uint32"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token0", "outputs": [{"type": "address"}],
     "stateMutability": "view", "type": "function"},
]

ROUTER_ABI = [
    {"inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}],
     "name": "getAmountsOut", "outputs": [{"type": "uint256[]"}],
     "stateMutability": "view", "type": "function"},
]

# ─── Constants ──────────────────────────────────────────────────────────────
WPLS         = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
V1_FACTORY   = Web3.to_checksum_address("0x1715a3E4A142d8b698131108995174F37aEBA10D")
V2_FACTORY   = Web3.to_checksum_address("0x29eA7545DEf87022BAdc76323F373EA1e707C523")
V1_ROUTER    = Web3.to_checksum_address("0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02")
V2_ROUTER    = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")
AFFECTION    = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
TGSV8        = Web3.to_checksum_address("0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32")
JOEY         = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
ZERO_ADDR    = "0x" + "0" * 40


def safe_call(contract, fn_name, *args):
    try:
        return getattr(contract.functions, fn_name)(*args).call()
    except Exception:
        return None


def get_pair_info(factory_addr, token_addr, against=WPLS):
    factory = w3.eth.contract(address=factory_addr, abi=FACTORY_ABI)
    pair_addr = safe_call(factory, "getPair", token_addr, against)
    if not pair_addr or pair_addr == ZERO_ADDR:
        return None
    pair = w3.eth.contract(address=Web3.to_checksum_address(pair_addr), abi=PAIR_ABI)
    reserves = safe_call(pair, "getReserves")
    token0 = safe_call(pair, "token0")
    if reserves is None or token0 is None:
        return None
    r0, r1, _ = reserves
    if token0.lower() == token_addr.lower():
        return {"pair": pair_addr, "r_token": int(r0), "r_wpls": int(r1)}
    return {"pair": pair_addr, "r_token": int(r1), "r_wpls": int(r0)}


def get_amounts_out(router_addr, amount_in, path):
    router = w3.eth.contract(address=router_addr, abi=ROUTER_ABI)
    try:
        return router.functions.getAmountsOut(amount_in, path).call()[-1]
    except Exception:
        return 0


def atomic_write(path, data):
    """Write JSON atomically via temp file + rename."""
    dir_name = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def scan_token_onchain(addr_str):
    """Read on-chain state for one token. Returns dict of findings."""
    addr = Web3.to_checksum_address(addr_str)
    erc = w3.eth.contract(address=addr, abi=ERC20_ABI)
    tt  = w3.eth.contract(address=addr, abi=ERC20_ABI + TREASURY_EXTRA_ABI)

    r = {
        "address":        addr_str,
        "totalSupply":    0,
        "decimals":       18,
        "parent":         None,
        "debenture":      None,
        "selfBalance":    0,
        "parentBalance":  0,
        "joeyBalance":    0,
        "tgsv8Balance":   0,
        "v1_pair":        None,
        "v2_pair":        None,
        "pls_per_token":  0,
        "v1_out":         0,
        "v2_out":         0,
    }

    r["totalSupply"] = safe_call(erc, "totalSupply") or 0
    r["decimals"]    = safe_call(erc, "decimals") or 18
    r["joeyBalance"] = safe_call(erc, "balanceOf", JOEY) or 0
    r["tgsv8Balance"]= safe_call(erc, "balanceOf", TGSV8) or 0
    r["parent"]      = safe_call(tt, "Parent")
    r["debenture"]   = safe_call(tt, "Debenture")
    r["selfBalance"] = safe_call(erc, "balanceOf", addr) or 0

    if r["parent"] and r["parent"] != ZERO_ADDR:
        parent_erc = w3.eth.contract(
            address=Web3.to_checksum_address(r["parent"]), abi=ERC20_ABI)
        r["parentBalance"] = safe_call(parent_erc, "balanceOf", addr) or 0

    r["v1_pair"] = get_pair_info(V1_FACTORY, addr)
    r["v2_pair"] = get_pair_info(V2_FACTORY, addr)

    one = 10 ** r["decimals"]
    r["v1_out"] = get_amounts_out(V1_ROUTER, one, [addr, WPLS]) if r["v1_pair"] else 0
    r["v2_out"] = get_amounts_out(V2_ROUTER, one, [addr, WPLS]) if r["v2_pair"] else 0
    r["pls_per_token"] = max(r["v1_out"], r["v2_out"])

    return r


def classify_opportunities(label, token_info, chain_data):
    """Given a token's master info + on-chain data, return opportunity list."""
    opps = []
    one = 10 ** chain_data["decimals"]

    # TREASURY_CLAIM: self-balance > 0 and token has DEX pair
    if chain_data["selfBalance"] > 0 and chain_data["pls_per_token"] > 0:
        qty = chain_data["selfBalance"] / one
        val = qty * (chain_data["pls_per_token"] / 1e18)
        opps.append({
            "type": "TREASURY_CLAIM",
            "token": label,
            "address": chain_data["address"],
            "estimated_pls": val,
            "desc": f"{qty:.2f} tokens self-backing, ~{val:,.0f} PLS",
        })

    # MINT_CLAIM_LOOP: Debenture == True (V2 Federal spine target)
    if chain_data["debenture"] is True and chain_data["parent"] and chain_data["parent"] != ZERO_ADDR:
        opps.append({
            "type": "MINT_CLAIM_LOOP",
            "token": label,
            "address": chain_data["address"],
            "parent": chain_data["parent"],
            "estimated_pls": 0,  # depends on iterations + swap value
            "desc": f"Debenture=True, mint-claim loop open. Parent={chain_data['parent'][:10]}...",
        })

    # PARENT_BACKING: holds parent tokens
    if chain_data["parentBalance"] > 0 and chain_data["parent"] and chain_data["parent"] != ZERO_ADDR:
        parent_cs = Web3.to_checksum_address(chain_data["parent"])
        p_v1 = get_amounts_out(V1_ROUTER, int(1e18), [parent_cs, WPLS])
        p_v2 = get_amounts_out(V2_ROUTER, int(1e18), [parent_cs, WPLS])
        p_pls = max(p_v1, p_v2)
        if p_pls > 0:
            val = (chain_data["parentBalance"] / 1e18) * (p_pls / 1e18)
            opps.append({
                "type": "PARENT_BACKING",
                "token": label,
                "address": chain_data["address"],
                "estimated_pls": val,
                "desc": f"Holds {chain_data['parentBalance']/1e18:.2f} parent tokens, ~{val:,.0f} PLS",
            })

    # CROSS_DEX_ARB: spread between V1 and V2
    v1, v2 = chain_data["v1_out"], chain_data["v2_out"]
    if v1 > 0 and v2 > 0:
        spread = abs(v1 - v2) / min(v1, v2) * 100
        if spread > 0.5:
            buy_dex = "V2" if v2 < v1 else "V1"
            sell_dex = "V1" if buy_dex == "V2" else "V2"
            opps.append({
                "type": "CROSS_DEX_ARB",
                "token": label,
                "address": chain_data["address"],
                "estimated_pls": 0,
                "desc": f"{spread:.2f}% spread: buy {buy_dex}, sell {sell_dex}",
            })

    return opps


def main():
    parser = argparse.ArgumentParser(description="Treasury Recon Scanner")
    parser.add_argument("--data-dir", default="data", help="Data directory path")
    parser.add_argument("--v2-only", action="store_true", help="Scan V2 Federal tokens only (fast)")
    parser.add_argument("--top", type=int, default=0, help="Show only top N opportunities")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of tokens to scan")
    args = parser.parse_args()

    data_dir = args.data_dir
    block = w3.eth.block_number
    print(f"═══ TREASURY RECON — Block {block} ═══")
    print(f"RPC: {RPC_READ}\n")

    # Load data files
    master_path = os.path.join(data_dir, "token_master.json")
    v2_path     = os.path.join(data_dir, "v2_federal_tokens.json")

    if os.path.exists(master_path):
        with open(master_path) as f:
            master_data = json.load(f)
            master = master_data.get("tokens", {})
        print(f"Loaded token_master.json: {len(master)} tokens")
    else:
        print(f"WARNING: {master_path} not found. Run with spine tracker data first.")
        master = {}

    # Determine scan targets
    if args.v2_only:
        if os.path.exists(v2_path):
            with open(v2_path) as f:
                v2_data = json.load(f)
            targets = {t["address"].lower(): t["symbol"] for t in v2_data["tokens"]}
            print(f"V2-only mode: scanning {len(targets)} Federal tokens")
        else:
            print(f"ERROR: {v2_path} not found")
            return
    else:
        # Scan everything in master that has a factory version (V1/V2/V3/V4)
        # Plus all known treasury/ecosystem tokens
        targets = {}
        for addr, info in master.items():
            label = info.get("symbol") or info.get("name") or addr[:10]
            targets[addr] = label
        print(f"Full scan: {len(targets)} tokens")

    if args.limit > 0:
        targets = dict(list(targets.items())[:args.limit])
        print(f"Limited to {len(targets)} tokens")

    # ─── Scan ───────────────────────────────────────────────────────────
    results = {}
    all_opps = []
    scanned = 0
    errors = 0
    t0 = time.time()

    for addr, label in targets.items():
        scanned += 1
        if scanned % 25 == 0:
            elapsed = time.time() - t0
            rate = scanned / elapsed if elapsed > 0 else 0
            print(f"  ... {scanned}/{len(targets)} ({rate:.1f} tok/s)")

        try:
            chain_data = scan_token_onchain(addr)
            token_info = master.get(addr, {})
            opps = classify_opportunities(label, token_info, chain_data)

            results[addr] = {
                "label": label,
                "chain_data": chain_data,
                "opportunities": opps,
            }

            for opp in opps:
                all_opps.append(opp)

            # Status line for interesting finds
            if chain_data["debenture"] is True:
                print(f"  ★ {label:16s} | DEB=True | pls={chain_data['pls_per_token']/1e18:.4f}")
            elif chain_data["selfBalance"] > 0:
                qty = chain_data["selfBalance"] / (10 ** chain_data["decimals"])
                print(f"  ◆ {label:16s} | selfBal={qty:.2f}")

        except Exception as e:
            errors += 1
            if scanned <= 10 or errors <= 5:
                print(f"  ✗ {label:16s} | ERROR: {e}")

    elapsed = time.time() - t0
    print(f"\nScan complete: {scanned} tokens in {elapsed:.1f}s ({errors} errors)")

    # ─── Sort & display opportunities ───────────────────────────────────
    all_opps.sort(key=lambda x: x.get("estimated_pls", 0), reverse=True)

    print(f"\n═══ OPPORTUNITY RANKING ═══")
    show_n = args.top if args.top > 0 else min(len(all_opps), 30)
    for i, opp in enumerate(all_opps[:show_n], 1):
        est = f"~{opp['estimated_pls']:,.0f} PLS" if opp["estimated_pls"] > 0 else "TBD"
        print(f"  {i:3d}. [{opp['type']:18s}] {opp['token']:16s} — {est}")
        print(f"       {opp['desc']}")

    # ─── Stats ──────────────────────────────────────────────────────────
    n_deb   = sum(1 for r in results.values() if r["chain_data"]["debenture"] is True)
    n_pairs = sum(1 for r in results.values()
                  if r["chain_data"]["v1_pair"] or r["chain_data"]["v2_pair"])
    n_back  = sum(1 for r in results.values()
                  if r["chain_data"]["selfBalance"] > 0 or r["chain_data"]["parentBalance"] > 0)
    total_est = sum(o.get("estimated_pls", 0) for o in all_opps)

    by_type = defaultdict(int)
    for o in all_opps:
        by_type[o["type"]] += 1

    print(f"\n═══ SUMMARY ═══")
    print(f"  Tokens scanned:      {scanned}")
    print(f"  With Debenture=True: {n_deb}  (mint-claim loop candidates)")
    print(f"  With DEX pairs:      {n_pairs}")
    print(f"  With backing:        {n_back}")
    print(f"  Total opportunities: {len(all_opps)}")
    for t, c in sorted(by_type.items()):
        print(f"    {t:20s}: {c}")
    print(f"  Estimated total PLS: ~{total_est:,.0f}")

    # ─── Write results ──────────────────────────────────────────────────
    recon_out = os.path.join(data_dir, "recon_results.json")
    atomic_write(recon_out, {
        "block": block,
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tokens_scanned": scanned,
        "errors": errors,
        "summary": {
            "debenture_true": n_deb,
            "with_dex_pairs": n_pairs,
            "with_backing": n_back,
            "total_opportunities": len(all_opps),
            "estimated_total_pls": total_est,
        },
        "results": results,
    })
    print(f"\n  Wrote {recon_out}")

    opp_out = os.path.join(data_dir, "spine_opportunities.json")
    atomic_write(opp_out, {
        "block": block,
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(all_opps),
        "estimated_total_pls": total_est,
        "opportunities": all_opps,
    })
    print(f"  Wrote {opp_out}")

    # Update v2_federal_tokens with live Debenture data
    if os.path.exists(v2_path):
        with open(v2_path) as f:
            v2_data = json.load(f)
        for tok in v2_data["tokens"]:
            addr_low = tok["address"].lower()
            if addr_low in results:
                cd = results[addr_low]["chain_data"]
                tok["debenture"] = cd["debenture"]
                tok["last_checked"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                tok["selfBalance"] = str(cd["selfBalance"])
                tok["pls_per_token"] = cd["pls_per_token"] / 1e18 if cd["pls_per_token"] else 0
        atomic_write(v2_path, v2_data)
        print(f"  Updated {v2_path} with live Debenture data")

    print(f"\n═══ RECON COMPLETE ═══")


if __name__ == "__main__":
    main()
