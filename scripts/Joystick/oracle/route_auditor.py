"""
route_auditor.py — Payment route validator and expanded token discovery.

Before each arb scan cycle, checks which payment routes are actually
funded (Joey holds the payment token) and which should be skipped.
Also expands token discovery beyond SEED_LAUS + MAP QINGs by pulling
from token_master.json and recon_results.json.

This prevents:
  - Wasted RPC calls scanning pDAI routes when pDAI balance = 0
  - Missing arb opportunities on tokens not in the seed list
  - Silent failures when payment token liquidity is zero
"""
import json
import logging
import os

from web3 import Web3

from ..core.config import (
    JOEY_WALLET, AFFECTION, WPLS,
    SEED_LAUS,
)
from ..core.chain import erc20, safe, w3_read

log = logging.getLogger(__name__)

# All known payment tokens and their labels
# Order matters: first match wins in scanner's rate check
PAYMENT_REGISTRY = [
    {
        "label":   "AFFECTION",
        "address": AFFECTION,
        "min_balance_wei": 1 * 10**18,  # Need at least 1 AFF to arb
        "acquisition_hint": "Engine 1 compound loop or PulseX buy",
    },
    {
        "label":   "pDAI",
        "address": Web3.to_checksum_address("0xefD766cCb38EaF1dfd701853BFCe31359239F305"),
        "min_balance_wei": 1 * 10**18,
        "acquisition_hint": "Buy on PulseX: WPLS → pDAI",
    },
    {
        "label":   "pUSDC",
        "address": Web3.to_checksum_address("0x015D38573d2feeb82e7ad5187aB8c1D52810B880"),
        "min_balance_wei": 1 * 10**18,
        "acquisition_hint": "Buy on PulseX: WPLS → pUSDC",
    },
    {
        "label":   "WPLS",
        "address": WPLS,
        "min_balance_wei": 100 * 10**18,  # Need meaningful WPLS
        "acquisition_hint": "Deposit native PLS via WPLS.deposit()",
    },
]

# Data files that may contain additional token addresses
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TOKEN_MASTER_PATH  = os.path.join(DATA_DIR, "token_master.json")
RECON_RESULTS_PATH = os.path.join(DATA_DIR, "recon_results.json")


def audit_payment_routes() -> dict:
    """
    Check which payment routes are funded and return status.

    Returns:
        {
            "funded": [{"label": "AFFECTION", "address": "0x...", "balance_wei": 88e18}, ...],
            "unfunded": [{"label": "pDAI", "address": "0x...", "hint": "Buy on PulseX..."}, ...],
            "funded_addresses": ["0x24F015...", ...],  # Quick filter list for scanner
        }
    """
    funded = []
    unfunded = []
    funded_addrs = []

    for entry in PAYMENT_REGISTRY:
        token = erc20(entry["address"])
        balance = safe(token, "balanceOf", JOEY_WALLET) or 0

        if balance >= entry["min_balance_wei"]:
            funded.append({
                "label":       entry["label"],
                "address":     entry["address"],
                "balance_wei": balance,
                "balance_human": f"{balance / 1e18:.4f}",
            })
            funded_addrs.append(entry["address"])
            log.debug("Route %s: FUNDED (%.4f)", entry["label"], balance / 1e18)
        else:
            unfunded.append({
                "label":   entry["label"],
                "address": entry["address"],
                "balance_wei": balance,
                "hint":    entry["acquisition_hint"],
            })
            log.debug("Route %s: UNFUNDED (%.4f < min)", entry["label"], balance / 1e18)

    if not funded:
        log.warning("NO payment routes funded — arb engine will find zero opportunities")

    return {
        "funded":           funded,
        "unfunded":         unfunded,
        "funded_addresses": funded_addrs,
    }


def discover_extra_tokens() -> list[tuple[str, str]]:
    """
    Pull additional token addresses from data files beyond SEED_LAUS.

    Sources:
      - data/token_master.json  (1,282 tokens from prior sessions)
      - data/recon_results.json (tokens with treasury backing)

    Returns list of (label, checksum_address) tuples.
    Only includes tokens that have DEX pairs noted in the data.
    """
    extras = []
    seen = {addr.lower() for _, addr in SEED_LAUS}

    # token_master.json — massive token list
    if os.path.exists(TOKEN_MASTER_PATH):
        try:
            with open(TOKEN_MASTER_PATH) as f:
                master = json.load(f)

            for addr, info in master.items():
                addr_lower = addr.lower()
                if addr_lower in seen:
                    continue

                # Only include tokens that have a known DEX pair
                # (no pair = can't sell = can't arb)
                has_pair = False
                if isinstance(info, dict):
                    has_pair = bool(
                        info.get("v1_pair") or info.get("v2_pair")
                        or info.get("pls_per_token", 0) > 0
                    )

                if has_pair:
                    label = info.get("symbol", info.get("name", f"TM-{addr[:8]}"))
                    try:
                        cs = Web3.to_checksum_address(addr)
                        extras.append((f"TM:{label}", cs))
                        seen.add(addr_lower)
                    except Exception:
                        pass

            log.info("token_master.json: %d extra tokens with DEX pairs", len(extras))
        except Exception as exc:
            log.debug("token_master.json load failed: %s", exc)

    # recon_results.json — tokens with confirmed treasury opportunities
    recon_extras = 0
    if os.path.exists(RECON_RESULTS_PATH):
        try:
            with open(RECON_RESULTS_PATH) as f:
                recon = json.load(f)

            for addr, data in recon.items():
                addr_lower = addr.lower()
                if addr_lower in seen:
                    continue

                # Include if has chain_data with a DEX pair
                chain = data.get("chain_data", {})
                has_pair = bool(chain.get("v1_pair") or chain.get("v2_pair"))

                if has_pair:
                    label = data.get("label", f"RECON-{addr[:8]}")
                    try:
                        cs = Web3.to_checksum_address(addr)
                        extras.append((f"RECON:{label}", cs))
                        seen.add(addr_lower)
                        recon_extras += 1
                    except Exception:
                        pass

            log.info("recon_results.json: %d extra tokens with DEX pairs", recon_extras)
        except Exception as exc:
            log.debug("recon_results.json load failed: %s", exc)

    return extras


def route_summary() -> str:
    """Human-readable summary for --status display."""
    audit = audit_payment_routes()
    lines = ["Payment Route Status:"]
    for r in audit["funded"]:
        lines.append(f"  + {r['label']}: {r['balance_human']} tokens")
    for r in audit["unfunded"]:
        lines.append(f"  - {r['label']}: unfunded -> {r['hint']}")

    extras = discover_extra_tokens()
    lines.append(f"\nExpanded Discovery: {len(extras)} additional tokens from data files")
    lines.append(f"Total scan pool: {len(SEED_LAUS) + len(extras)} tokens (seed + data)")
    return "\n".join(lines)
