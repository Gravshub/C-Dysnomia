"""
Seed GIBS/AFF V2 LP pair.
Run via: python -m scripts.Joystick.tools.seed_gibs_aff_lp
"""
import sys, os, time

# Ensure correct path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from web3 import Web3
from scripts.Joystick.core.config import (
    GIBS_LAU, AFFECTION, JOYSTICK_HUB, JOEY_WALLET, PULSEX_V2_ROUTER,
)
from scripts.Joystick.core.chain import safe, erc20, joystick_hub, w3_submit, w3_read
from scripts.Joystick.core.executor import send_tx, approve_if_needed

cs = Web3.to_checksum_address

SEED_GIBS = 175
SEED_AFF = 200
GIBS_AFF_V2 = "0x1E2fAeF811b8eA8dC5E0dEEe2c3b0E355A7d7EA0"

def main():
    hub = joystick_hub(w3=w3_submit)
    aff_cs = cs(AFFECTION)
    gibs_cs = cs(GIBS_LAU)
    hub_addr = cs(JOYSTICK_HUB)
    router_addr = cs(PULSEX_V2_ROUTER)

    print("=== Step 1: Prime 175 GIBS (costs 175 AFF from Hub) ===")
    r = send_tx(
        hub.functions.primeGibs(SEED_GIBS),
        f"primeGibs({SEED_GIBS}) [GIBS/AFF LP seed]",
        gas_tier="fast",
    )
    if r:
        print(f"  TX: 0x{r['transactionHash'].hex()}")
        print(f"  Block: {r['blockNumber']} Gas: {r['gasUsed']}")
    else:
        print("  FAILED"); return

    print("\n=== Step 2: Withdraw 175 GIBS from Hub → Joey ===")
    r = send_tx(
        hub.functions.withdraw(gibs_cs, SEED_GIBS * 10**18),
        f"withdraw({SEED_GIBS} GIBS)",
        skip_simulate=True, fixed_gas=100_000,
    )
    if r:
        print(f"  TX: 0x{r['transactionHash'].hex()}")
    else:
        print("  FAILED"); return

    print(f"\n=== Step 3: Withdraw {SEED_AFF} AFF from Hub → Joey ===")
    r = send_tx(
        hub.functions.withdraw(aff_cs, SEED_AFF * 10**18),
        f"withdraw({SEED_AFF} AFF)",
        skip_simulate=True, fixed_gas=100_000,
    )
    if r:
        print(f"  TX: 0x{r['transactionHash'].hex()}")
    else:
        print("  FAILED"); return

    joey_gibs = (safe(erc20(GIBS_LAU), "balanceOf", JOEY_WALLET) or 0) / 1e18
    joey_aff = (safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0) / 1e18
    print(f"\n  Joey GIBS: {joey_gibs:.2f}  AFF: {joey_aff:.2f}")

    print("\n=== Step 4: Approve GIBS + AFF → V2 Router ===")
    MAX_UINT = 2**256 - 1
    gibs_c = w3_submit.eth.contract(address=gibs_cs, abi=erc20(GIBS_LAU).abi)
    aff_c = w3_submit.eth.contract(address=aff_cs, abi=erc20(AFFECTION).abi)
    r = approve_if_needed(gibs_c, router_addr, MAX_UINT, "GIBS→Router")
    if r: print(f"  GIBS approved")
    r = approve_if_needed(aff_c, router_addr, MAX_UINT, "AFF→Router")
    if r: print(f"  AFF approved")

    print(f"\n=== Step 5: addLiquidity({SEED_GIBS} GIBS + {SEED_AFF} AFF) ===")
    ROUTER_ABI = [
        {"inputs":[
            {"name":"tokenA","type":"address"},{"name":"tokenB","type":"address"},
            {"name":"amountADesired","type":"uint256"},{"name":"amountBDesired","type":"uint256"},
            {"name":"amountAMin","type":"uint256"},{"name":"amountBMin","type":"uint256"},
            {"name":"to","type":"address"},{"name":"deadline","type":"uint256"}
        ],"name":"addLiquidity","outputs":[
            {"name":"amountA","type":"uint256"},{"name":"amountB","type":"uint256"},
            {"name":"liquidity","type":"uint256"}
        ],"type":"function"},
    ]
    router = w3_submit.eth.contract(address=router_addr, abi=ROUTER_ABI)

    gibs_amt = SEED_GIBS * 10**18
    aff_amt = SEED_AFF * 10**18

    r = send_tx(
        router.functions.addLiquidity(
            gibs_cs, aff_cs,
            gibs_amt, aff_amt,
            int(gibs_amt * 95 / 100), int(aff_amt * 95 / 100),
            JOEY_WALLET, int(time.time()) + 300,
        ),
        f"addLiquidity({SEED_GIBS} GIBS + {SEED_AFF} AFF)",
    )
    if r:
        print(f"  TX: 0x{r['transactionHash'].hex()}")
        print(f"  Block: {r['blockNumber']} Gas: {r['gasUsed']}")
    else:
        print("  FAILED"); return

    # Final state
    from scripts.Joystick.core.chain import pair_contract
    pc = pair_contract(cs(GIBS_AFF_V2))
    reserves = safe(pc, "getReserves")
    t0 = safe(pc, "token0")
    if t0.lower() == AFFECTION.lower():
        aff_r, gibs_r = reserves[0], reserves[1]
    else:
        gibs_r, aff_r = reserves[0], reserves[1]
    hub_aff = (safe(erc20(AFFECTION), "balanceOf", JOYSTICK_HUB) or 0) / 1e18

    print(f"\n=== Final State ===")
    print(f"GIBS/AFF V2: {gibs_r/1e18:.2f} GIBS / {aff_r/1e18:.2f} AFF")
    print(f"Price: 1 GIBS = {aff_r/gibs_r:.4f} AFF")
    print(f"Hub AFF: {hub_aff:.2f}")
    print(f"Pool +{SEED_GIBS} GIBS +{SEED_AFF} AFF seeded")


if __name__ == "__main__":
    main()
