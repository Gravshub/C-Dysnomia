#!/usr/bin/env python3
"""
Deploy GARBAGE pDAI Printer Token on PulseChain.

DaiHard-fork 10% tax token. Tax -> PLS -> pDAI -> dividend holders.
Creates 13 LP pairs on PulseX V2, launches trading, burns all LP tokens.

Stages:
  0  Pre-flight checks (balances, nonce, gas, partner tokens)
  1  Compile & deploy GARBAGE contract
  2  Buy FED (only missing partner token)
  3  Create 13 LP pairs (WPLS via addLP, rest manual)
  4  Launch trading
  5  Burn all LP tokens to 0x...369
  6  Verify & persist (receipt JSON, contracts.json, .env)

Usage:
  python scripts/deploy_garbage.py --dry-run      # simulate, no sends
  python scripts/deploy_garbage.py                 # full deploy
  python scripts/deploy_garbage.py --stage 3       # resume from stage 3
"""
import os, sys, json, time, argparse, subprocess
from pathlib import Path

# ── Auto-install ───────────────────────────────────────────────────────────
def _pkg(pip, imp):
    try: __import__(imp)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pip,
                               "-q", "--break-system-packages"])
for _p, _i in [("py-solc-x","solcx"),("python-dotenv","dotenv"),("web3","web3")]:
    _pkg(_p, _i)

from solcx import compile_standard, install_solc, get_installed_solc_versions
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv

# ── Paths ──────────────────────────────────────────────────────────────────
REPO       = Path(__file__).resolve().parent.parent
SOL_FILE   = REPO / "contracts" / "garbage" / "GARBAGE.sol"
STATE_F    = REPO / "data" / "garbage_deploy_state.json"
ABI_F      = REPO / "data" / "garbage_abi.json"
RECEIPT_F  = REPO / "data" / "garbage_deploy_receipt.json"
CONTR_F    = REPO / "scripts" / "Joystick" / "data" / "contracts.json"

# ── Chain config ───────────────────────────────────────────────────────────
RPC_URL    = "https://rpc.pulsechain.com"       # single RPC for deploy
RPC_READ   = "https://rpc-pulsechain.g4mm4.io"  # pre-flight reads only
CHAIN      = 369
SOLC_VER   = "0.8.21"
GAS_X      = 2.5                    # gas estimate multiplier (PulseChain needs headroom)
GAS_CEIL   = 2_000_000 * 10**9      # max gas price in impulses
TX_TIMEOUT = 600                     # receipt wait seconds

cs = Web3.to_checksum_address
JOEY  = cs("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
BURN  = cs("0x0000000000000000000000000000000000000369")
PLS_FLOOR = 100_000 * 10**18

# ── Token addresses ────────────────────────────────────────────────────────
WPLS      = cs("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
pDAI      = cs("0x6B175474E89094C44Da98b954EedeAC495271d0F")
GIBS      = cs("0x66A08AA12da955EB63D7aC121a88b2B210A07B03")
N0T       = cs("0x4B5357bfB0aD2A5fDB07A0161fe2A367B7B7Ea89")
LIBERTAD  = cs("0x6784C1f63944f66749d7151C5e7aCb5591a5f64e")
Z07734    = cs("0x7Ca64bf8C454D262Cde31610A5F2aFEe6837FABC")
GL0B0S    = cs("0x13c7E24f133E07Cf895f7230DfFE564eB4402E4E")
ATROPA    = cs("0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6")
PRVX      = cs("0xf6f8db0aba00007681f8faf16a0fda1c9b030b11")
VOID_TKN  = cs("0x965B0d74591bF30327075A247C47dBf487dCff08")
WM        = cs("0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29")
FED       = cs("0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff")
AFF       = cs("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
ROUTER_V2 = cs("0x165C3410fC91EF562C50559f7d2289fEbed552d9")
FACT_V2   = cs("0x29eA7545DEf87022BAdc76323F373EA1e707C523")

# ── LP pair definitions ────────────────────────────────────────────────────
# GARBAGE has 9 decimals.  garb_whole is in whole tokens (contract multiplies
# by 10^9 for addLP; we multiply manually for direct transfers).
G_DEC = 9
G_FAC = 10 ** G_DEC

# NOTE ON addLP vs MANUAL:
# The DaiHard addLP() only works for the WPLS (ETH) branch because the
# contract never approves the V2 router for partner tokens.  For all non-WPLS
# pairs we create liquidity manually: factory.createPair -> setPair ->
# direct token transfers to pair address -> pair.mint().  This is safe and
# gas-efficient.
#
# Order: WPLS first (sets lpPair, required for swapBack tax routing),
# then pDAI, then the rest.

#       symbol        addr        garb_whole      partner_wei                via_addLP
PAIRS = [
    ("WPLS",      WPLS,       10_000_000,   200_000 * 10**18,             True),
    ("pDAI",      pDAI,      100_000_000,    13_234 * 10**18,             False),
    ("GIBS",      GIBS,        2_478_437,       275 * 10**18,             False),
    ("n0T",       N0T,         4_928_612,     30882 * 10**16,             False),  # 308.82
    ("Libertad",  LIBERTAD,    2_130_700,     1_300 * 10**18,             False),
    ("07734",     Z07734,        333_327,       391 * 10**18,             False),
    ("Gl0b0s",    GL0B0S,        369_270,       110 * 10**18,             False),
    ("ATROPA",    ATROPA,        493_036,         3 * 10**18,             False),
    ("PRVX",      PRVX,          413_500,     1_000 * 10**18,             False),
    ("VOID",      VOID_TKN,     240_292,         5 * 10**18,             False),
    ("WM",        WM,            119_500,       200 * 10**18,             False),
    ("FED",       FED,           246_750,     3_500 * 10**18,             False),
    ("AFFECTION", AFF,            24_695,        10 * 10**18,             False),
]
ZERO_ADDR = "0x" + "0" * 40

# ── Minimal ABIs ───────────────────────────────────────────────────────────
ERC20_ABI = [
    {"type":"function","name":"balanceOf","inputs":[{"name":"","type":"address"}],
     "outputs":[{"type":"uint256"}],"stateMutability":"view"},
    {"type":"function","name":"transfer","inputs":[{"name":"","type":"address"},
     {"name":"","type":"uint256"}],"outputs":[{"type":"bool"}],"stateMutability":"nonpayable"},
    {"type":"function","name":"approve","inputs":[{"name":"","type":"address"},
     {"name":"","type":"uint256"}],"outputs":[{"type":"bool"}],"stateMutability":"nonpayable"},
    {"type":"function","name":"allowance","inputs":[{"name":"","type":"address"},
     {"name":"","type":"address"}],"outputs":[{"type":"uint256"}],"stateMutability":"view"},
    {"type":"function","name":"totalSupply","inputs":[],"outputs":[{"type":"uint256"}],
     "stateMutability":"view"},
    {"type":"function","name":"name","inputs":[],"outputs":[{"type":"string"}],
     "stateMutability":"view"},
    {"type":"function","name":"symbol","inputs":[],"outputs":[{"type":"string"}],
     "stateMutability":"view"},
]

FACTORY_ABI = [
    {"type":"function","name":"createPair","inputs":[{"name":"","type":"address"},
     {"name":"","type":"address"}],"outputs":[{"type":"address"}],"stateMutability":"nonpayable"},
    {"type":"function","name":"getPair","inputs":[{"name":"","type":"address"},
     {"name":"","type":"address"}],"outputs":[{"type":"address"}],"stateMutability":"view"},
]

PAIR_ABI = [
    # PulseX V2 uses mint(address,address) not standard mint(address)
    {"type":"function","name":"mint","inputs":[{"name":"","type":"address"},
     {"name":"","type":"address"}],"outputs":[{"type":"uint256"}],
     "stateMutability":"nonpayable"},
    {"type":"function","name":"getReserves","inputs":[],"outputs":[
     {"type":"uint112"},{"type":"uint112"},{"type":"uint32"}],"stateMutability":"view"},
    {"type":"function","name":"balanceOf","inputs":[{"name":"","type":"address"}],
     "outputs":[{"type":"uint256"}],"stateMutability":"view"},
    {"type":"function","name":"transfer","inputs":[{"name":"","type":"address"},
     {"name":"","type":"uint256"}],"outputs":[{"type":"bool"}],"stateMutability":"nonpayable"},
    {"type":"function","name":"token0","inputs":[],"outputs":[{"type":"address"}],
     "stateMutability":"view"},
    {"type":"function","name":"token1","inputs":[],"outputs":[{"type":"address"}],
     "stateMutability":"view"},
    {"type":"function","name":"totalSupply","inputs":[],"outputs":[{"type":"uint256"}],
     "stateMutability":"view"},
]

ROUTER_ABI = [
    {"type":"function","name":"swapExactETHForTokens","inputs":[
     {"name":"","type":"uint256"},{"name":"","type":"address[]"},
     {"name":"","type":"address"},{"name":"","type":"uint256"}],
     "outputs":[{"type":"uint256[]"}],"stateMutability":"payable"},
    {"type":"function","name":"getAmountsOut","inputs":[
     {"name":"","type":"uint256"},{"name":"","type":"address[]"}],
     "outputs":[{"type":"uint256[]"}],"stateMutability":"view"},
    {"type":"function","name":"WPLS","inputs":[],"outputs":[{"type":"address"}],
     "stateMutability":"pure"},
]

# ═══════════════════════════════════════════════════════════════════════════
#  STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def load_state():
    if STATE_F.exists():
        return json.loads(STATE_F.read_text())
    return {"garbage_address": None, "distributor_address": None,
            "pairs": {}, "lp_burns": {}, "tx_log": [],
            "fed_bought": False, "launched": False}

def save_state(st):
    tmp = STATE_F.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2))
    os.replace(str(tmp), str(STATE_F))

def log_tx(st, stage, label, receipt):
    entry = {"stage": stage, "label": label,
             "tx": receipt["transactionHash"].hex(),
             "block": receipt["blockNumber"],
             "gas": receipt["gasUsed"]}
    st.setdefault("tx_log", []).append(entry)
    save_state(st)
    return entry

# ═══════════════════════════════════════════════════════════════════════════
#  TX HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def send_tx(w3, acct, fn, label, value=0, nonce=None, dry_run=False):
    """Simulate -> estimate_gas -> build -> sign -> send -> receipt (with retry)."""
    call_kw = {"from": acct.address}
    if value:
        call_kw["value"] = value

    # 1) Simulate via eth_call
    try:
        fn.call(call_kw)
    except Exception as e:
        raise RuntimeError(f"SIM REVERT [{label}]: {e}")

    # 2) Estimate gas
    gas_est = fn.estimate_gas(call_kw)
    gas_lim = int(gas_est * GAS_X)

    # 3) Gas price check — bump 25% above eth_gasPrice for reliable inclusion
    gas_price = int(w3.eth.gas_price * 125 / 100)
    if gas_price > GAS_CEIL:
        raise RuntimeError(f"Gas {gas_price/1e9:.0f} Beats > ceiling {GAS_CEIL/1e9:.0f}")

    cost_est = gas_lim * gas_price / 1e18
    print(f"    [{label}] est={gas_est:,}  lim={gas_lim:,}  ~{cost_est:.1f} PLS")

    if dry_run:
        print(f"    [{label}] DRY-RUN skip")
        return None, nonce

    if nonce is None:
        nonce = w3.eth.get_transaction_count(acct.address)

    # Retry loop: send, wait 300s, if dropped re-fetch nonce and retry
    for attempt in range(3):
        tx = fn.build_transaction({
            "from": acct.address, "nonce": nonce, "gas": gas_lim,
            "gasPrice": gas_price, "chainId": CHAIN, "value": value,
        })
        signed = acct.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"    [{label}] TX: 0x{h.hex()}  (attempt {attempt+1})")

        try:
            r = w3.eth.wait_for_transaction_receipt(h, timeout=300)
            if r["status"] != 1:
                raise RuntimeError(f"TX FAILED [{label}] 0x{h.hex()}")
            cost = r["gasUsed"] * r.get("effectiveGasPrice", gas_price) / 1e18
            print(f"    [{label}] OK  gas={r['gasUsed']:,}  cost={cost:.2f} PLS  blk={r['blockNumber']}")
            return r, nonce + 1
        except Exception as e:
            if "TimeExhausted" in type(e).__name__ or "Timeout" in str(type(e)):
                # Check if TX was actually mined
                try:
                    r = w3.eth.get_transaction_receipt(h)
                    if r and r["status"] == 1:
                        cost = r["gasUsed"] * r.get("effectiveGasPrice", gas_price) / 1e18
                        print(f"    [{label}] OK (late receipt)  blk={r['blockNumber']}")
                        return r, nonce + 1
                except Exception:
                    pass
                # TX dropped — refresh nonce and bump gas for retry
                new_nonce = w3.eth.get_transaction_count(acct.address)
                if new_nonce > nonce:
                    # Nonce advanced — TX was mined elsewhere or different TX used nonce
                    print(f"    [{label}] Nonce advanced {nonce}->{new_nonce}, TX may have landed")
                    nonce = new_nonce
                    # Try to get receipt one more time
                    import time as _t; _t.sleep(5)
                    try:
                        r = w3.eth.get_transaction_receipt(h)
                        if r:
                            cost = r["gasUsed"] * r.get("effectiveGasPrice", gas_price) / 1e18
                            print(f"    [{label}] Found receipt  status={r['status']}  blk={r['blockNumber']}")
                            if r["status"] != 1:
                                raise RuntimeError(f"TX FAILED [{label}]")
                            return r, nonce
                    except Exception:
                        pass
                    raise RuntimeError(f"TX lost [{label}] nonce advanced but no receipt")
                gas_price = int(gas_price * 130 / 100)  # bump 30% for retry
                print(f"    [{label}] Dropped, retrying with gas={gas_price}...")
                continue
            raise

    raise RuntimeError(f"TX failed after 3 attempts [{label}]")


def deploy_tx(w3, acct, abi, bytecode, args, label, dry_run=False):
    """Deploy contract.  Returns (address, receipt, nonce+1)."""
    fac = w3.eth.contract(abi=abi, bytecode=bytecode)
    ctor = fac.constructor(*args)

    gas_est = ctor.estimate_gas({"from": acct.address})
    # Deploy uses 1.5x multiplier (not 2.5x) — 26M gas limit was getting
    # dropped by PulseChain nodes.  Legacy gasPrice (not EIP-1559) matches
    # the pattern that successfully deployed JoystickHub + TGSv8.
    gas_lim = int(gas_est * 1.5)
    gas_price = w3.eth.gas_price
    if gas_price > GAS_CEIL:
        raise RuntimeError("Gas too high for deploy")

    cost_est = gas_lim * gas_price / 1e18
    print(f"    [{label}] est={gas_est:,}  lim={gas_lim:,}  ~{cost_est:.1f} PLS")

    if dry_run:
        print(f"    [{label}] DRY-RUN skip")
        return None, None, None

    nonce = w3.eth.get_transaction_count(acct.address)

    tx = ctor.build_transaction({
        "from": acct.address, "nonce": nonce, "gas": gas_lim,
        "gasPrice": gas_price, "chainId": CHAIN,
    })
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"    [{label}] TX: 0x{h.hex()}")

    r = w3.eth.wait_for_transaction_receipt(h, timeout=TX_TIMEOUT)
    if r["status"] != 1:
        raise RuntimeError(f"DEPLOY FAILED [{label}]")

    addr = r["contractAddress"]
    cost = r["gasUsed"] * r.get("effectiveGasPrice", gas_price) / 1e18
    print(f"    [{label}] DEPLOYED: {addr}  gas={r['gasUsed']:,}  cost={cost:.2f} PLS")
    return addr, r, nonce + 1


# ═══════════════════════════════════════════════════════════════════════════
#  STAGE 0: PRE-FLIGHT
# ═══════════════════════════════════════════════════════════════════════════

def stage0(w3, acct):
    print("\n" + "=" * 60)
    print("  [STAGE 0] Pre-flight checks")
    print("=" * 60)

    # Wallet identity
    assert acct.address.lower() == JOEY.lower(), f"Wrong wallet: {acct.address}"
    print(f"  Wallet: {acct.address}")

    # PLS balance
    bal = w3.eth.get_balance(JOEY)
    bal_pls = bal / 1e18
    print(f"  PLS:    {bal_pls:,.0f}")
    if bal < PLS_FLOOR:
        raise RuntimeError(f"PLS {bal_pls:.0f} < 100K floor")

    # Nonce
    nonce = w3.eth.get_transaction_count(JOEY)
    print(f"  Nonce:  {nonce}")

    # Gas price
    gp = w3.eth.gas_price
    print(f"  Gas:    {gp / 1e9:.0f} Beats ({gp} impulses)")
    if gp > GAS_CEIL:
        raise RuntimeError(f"Gas price too high")

    # Partner token balances
    print(f"  Partner token balances:")
    missing = []
    for sym, addr, _, pwei, via_addlp in PAIRS:
        if sym == "WPLS":
            # Covered by PLS balance (200K + gas)
            need_pls = pwei + 50_000 * 10**18  # 200K + 50K buffer
            if bal < need_pls:
                missing.append(f"  WPLS: need {need_pls/1e18:.0f} PLS, have {bal_pls:.0f}")
            else:
                print(f"    WPLS:      {bal_pls:>14,.2f}  (need ~250K incl gas) OK")
            continue
        if sym == "FED":
            # Will be bought in stage 2 — check but don't fail
            tok = w3.eth.contract(address=addr, abi=ERC20_ABI)
            tbal = tok.functions.balanceOf(JOEY).call()
            flag = "OK" if tbal >= pwei else "WILL BUY"
            print(f"    {sym:10s} {tbal/1e18:>14.4f}  (need {pwei/1e18:.4f}) {flag}")
            continue
        tok = w3.eth.contract(address=addr, abi=ERC20_ABI)
        tbal = tok.functions.balanceOf(JOEY).call()
        if tbal < pwei:
            missing.append(f"  {sym}: have {tbal/1e18:.4f}, need {pwei/1e18:.4f}")
        else:
            print(f"    {sym:10s} {tbal/1e18:>14.4f}  (need {pwei/1e18:.4f}) OK")

    if missing:
        print(f"\n  MISSING TOKENS:")
        for m in missing:
            print(f"    {m}")
        raise RuntimeError("Missing partner tokens — cannot proceed")

    # Source file
    if not SOL_FILE.exists():
        raise RuntimeError(f"GARBAGE.sol not found at {SOL_FILE}")

    print(f"\n  [STAGE 0] PASS\n")
    return nonce


# ═══════════════════════════════════════════════════════════════════════════
#  STAGE 1: COMPILE & DEPLOY
# ═══════════════════════════════════════════════════════════════════════════

def stage1(w3, acct, st, dry_run):
    print("\n" + "=" * 60)
    print("  [STAGE 1] Compile & Deploy GARBAGE")
    print("=" * 60)

    if st.get("garbage_address"):
        addr = st["garbage_address"]
        print(f"  Already deployed at {addr} -- skipping")
        return addr, json.loads(ABI_F.read_text()) if ABI_F.exists() else None

    # Ensure solc
    installed = [str(v) for v in get_installed_solc_versions()]
    if SOLC_VER not in installed:
        print(f"  Installing solc {SOLC_VER}...")
        install_solc(SOLC_VER)
    print(f"  solc {SOLC_VER} ready")

    # Compile (no optimizer — match DaiHard exactly)
    source = SOL_FILE.read_text()
    print(f"  Compiling GARBAGE.sol (no optimizer)...")
    compiled = compile_standard({
        "language": "Solidity",
        "sources": {"GARBAGE.sol": {"content": source}},
        "settings": {
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object",
                                              "evm.deployedBytecode.object"]}}
        }
    }, solc_version=SOLC_VER)

    cdata = compiled["contracts"]["GARBAGE.sol"]["GarbageTaxToken"]
    abi      = cdata["abi"]
    bytecode = cdata["evm"]["bytecode"]["object"]

    creation_len = len(bytecode) // 2
    deployed_bc  = cdata["evm"]["deployedBytecode"]["object"]
    deployed_len = len(deployed_bc) // 2
    print(f"  Creation bytecode:  {creation_len:,} bytes ({creation_len/1024:.1f} KB)")
    print(f"  Deployed bytecode:  {deployed_len:,} bytes ({deployed_len/1024:.1f} KB)")
    if deployed_len > 24_576:
        raise RuntimeError(f"EIP-170 exceeded: {deployed_len} > 24,576 bytes")

    # Save ABI
    ABI_F.parent.mkdir(parents=True, exist_ok=True)
    tmp = ABI_F.with_suffix(".tmp")
    tmp.write_text(json.dumps(abi, indent=2))
    os.replace(str(tmp), str(ABI_F))
    print(f"  ABI -> {ABI_F.relative_to(REPO)}")

    # Deploy
    #   constructor("GARBAGE", unicode"🗑️", 1_000_000_000, pDAI)
    ctor_args = ("GARBAGE", "\U0001f5d1\ufe0f", 1_000_000_000, pDAI)

    addr, receipt, _ = deploy_tx(w3, acct, abi, bytecode, ctor_args,
                                 "GarbageTaxToken", dry_run)

    if dry_run:
        print(f"  [STAGE 1] DRY-RUN complete")
        return None, abi

    # Verify on-chain state
    gc = w3.eth.contract(address=addr, abi=abi)
    name   = gc.functions.name().call()
    symbol = gc.functions.symbol().call()
    supply = gc.functions.totalSupply().call()
    jbal   = gc.functions.balanceOf(JOEY).call()
    dist   = gc.functions.distributor().call()

    expected = 1_000_000_000 * G_FAC
    print(f"  Verify: name={name}  symbol={symbol}")
    print(f"  Verify: totalSupply={supply}  expected={expected}")
    print(f"  Verify: balanceOf(joey)={jbal}")
    print(f"  Verify: distributor={dist}")
    assert supply == expected, f"Supply mismatch: {supply} != {expected}"
    assert jbal == expected, f"Balance mismatch: {jbal} != {expected}"

    # Persist
    st["garbage_address"] = addr
    st["distributor_address"] = dist
    log_tx(st, 1, "deploy", receipt)
    print(f"\n  [STAGE 1] GARBAGE deployed at {addr}")
    return addr, abi


# ═══════════════════════════════════════════════════════════════════════════
#  STAGE 2: BUY FED
# ═══════════════════════════════════════════════════════════════════════════

def stage2(w3, acct, st, dry_run):
    print("\n" + "=" * 60)
    print("  [STAGE 2] Buy FED")
    print("=" * 60)

    if st.get("fed_bought"):
        print(f"  FED already bought -- skipping")
        return

    fed_tok = w3.eth.contract(address=FED, abi=ERC20_ABI)
    fed_bal = fed_tok.functions.balanceOf(JOEY).call()
    needed = 3_500 * 10**18

    if fed_bal >= needed:
        print(f"  FED balance: {fed_bal/1e18:.2f} >= 3,500 -- skipping buy")
        st["fed_bought"] = True
        save_state(st)
        return

    shortfall = needed - fed_bal
    print(f"  FED balance: {fed_bal/1e18:.4f}  need: 3,500  shortfall: {shortfall/1e18:.2f}")

    # Quote PLS -> WPLS -> FED
    router = w3.eth.contract(address=ROUTER_V2, abi=ROUTER_ABI)
    path = [WPLS, FED]

    # Start with 6000 PLS budget (generous buffer over 4935 PLS estimate)
    pls_budget = 6_000 * 10**18
    try:
        amounts = router.functions.getAmountsOut(pls_budget, path).call()
        fed_out = amounts[-1]
    except Exception:
        raise RuntimeError("No WPLS/FED pair on V2 -- cannot quote FED price")

    if fed_out < shortfall:
        # Scale up budget proportionally + 10% buffer
        pls_budget = int(shortfall * pls_budget // fed_out * 110 // 100)
        amounts = router.functions.getAmountsOut(pls_budget, path).call()
        fed_out = amounts[-1]

    min_out = int(fed_out * 95 // 100)  # 5% slippage tolerance
    print(f"  Swap: {pls_budget/1e18:.0f} PLS -> ~{fed_out/1e18:.2f} FED  (min: {min_out/1e18:.2f})")

    deadline = int(time.time()) + 300
    fn = router.functions.swapExactETHForTokens(min_out, path, JOEY, deadline)
    receipt, _ = send_tx(w3, acct, fn, "Buy FED", value=pls_budget, dry_run=dry_run)

    if not dry_run:
        new_bal = fed_tok.functions.balanceOf(JOEY).call()
        print(f"  FED balance after: {new_bal/1e18:.4f}")
        st["fed_bought"] = True
        log_tx(st, 2, "buy_fed", receipt)

    print(f"  [STAGE 2] Done")


# ═══════════════════════════════════════════════════════════════════════════
#  STAGE 3: CREATE 13 LP PAIRS
# ═══════════════════════════════════════════════════════════════════════════

def _create_pair_addlp(w3, acct, garbage, garb_addr, sym, partner, garb_whole,
                       pls_value, nonce, st, dry_run):
    """Create WPLS pair via addLP (ETH branch).  Sets lpPair."""
    print(f"    Using addLP({garb_whole:,}, 0, WPLS) value={pls_value/1e18:.0f} PLS")
    fn = garbage.functions.addLP(garb_whole, 0, WPLS)
    receipt, nonce = send_tx(w3, acct, fn, f"addLP {sym}",
                             value=pls_value, nonce=nonce, dry_run=dry_run)
    if not dry_run:
        factory = w3.eth.contract(address=FACT_V2, abi=FACTORY_ABI)
        pair_addr = factory.functions.getPair(garb_addr, partner).call()
        st.setdefault("pairs", {})[sym] = {"address": pair_addr,
                                            "block": receipt["blockNumber"]}
        log_tx(st, 3, f"addLP_{sym}", receipt)
        print(f"    Pair: {pair_addr}")
    return nonce


def _create_pair_manual(w3, acct, garbage, garb_addr, sym, partner, garb_whole,
                        part_wei, nonce, st, dry_run):
    """Create non-WPLS pair manually: createPair -> setPair -> transfers -> mint."""
    garb_wei = garb_whole * G_FAC
    factory = w3.eth.contract(address=FACT_V2, abi=FACTORY_ABI)

    # Step 1: Create pair (or find existing)
    existing = factory.functions.getPair(garb_addr, partner).call()
    if existing != ZERO_ADDR:
        pair_addr = existing
        print(f"    Pair exists: {pair_addr}")
    else:
        if dry_run:
            print(f"    [DRY] Would createPair(GARBAGE, {sym})")
            print(f"    [DRY] Would setPair -> GARBAGE.transfer({garb_whole:,}) -> "
                  f"{sym}.transfer({part_wei/1e18:.4f}) -> pair.mint")
            return nonce

        fn = factory.functions.createPair(garb_addr, partner)
        receipt, nonce = send_tx(w3, acct, fn, f"createPair {sym}", nonce=nonce)
        # Extract pair address from PairCreated event log (more reliable than getPair
        # which can return stale data on PulseChain RPC)
        pair_addr = None
        for log_entry in receipt.get("logs", []):
            if log_entry["address"].lower() == FACT_V2.lower() and len(log_entry["data"]) >= 66:
                # PairCreated event: data contains pair address + allPairsLength
                pair_addr = Web3.to_checksum_address("0x" + log_entry["data"].hex()[24:64])
                break
        if not pair_addr or pair_addr == ZERO_ADDR:
            # Fallback to getPair with retry
            import time as _t
            _t.sleep(3)
            pair_addr = factory.functions.getPair(garb_addr, partner).call()
        if pair_addr == ZERO_ADDR:
            raise RuntimeError(f"createPair succeeded but pair address not found for {sym}")
        print(f"    Pair created: {pair_addr}")
        log_tx(st, 3, f"createPair_{sym}", receipt)

    if dry_run:
        print(f"    [DRY] Would setPair + transfers + mint for {sym}")
        return nonce

    # Step 2: Register pair (setPair -> dividend exempt before any transfers)
    fn = garbage.functions.setPair(pair_addr, True)
    receipt, nonce = send_tx(w3, acct, fn, f"setPair {sym}", nonce=nonce)
    log_tx(st, 3, f"setPair_{sym}", receipt)

    # Step 3: Transfer GARBAGE tokens to pair
    fn = garbage.functions.transfer(pair_addr, garb_wei)
    receipt, nonce = send_tx(w3, acct, fn, f"GARBAGE->{sym} pair", nonce=nonce)
    log_tx(st, 3, f"xfer_garb_{sym}", receipt)

    # Step 4: Transfer partner tokens to pair
    ptok = w3.eth.contract(address=partner, abi=ERC20_ABI)
    fn = ptok.functions.transfer(pair_addr, part_wei)
    receipt, nonce = send_tx(w3, acct, fn, f"{sym}->pair", nonce=nonce)
    log_tx(st, 3, f"xfer_part_{sym}", receipt)

    # Step 5: Mint LP tokens to Joey
    pair_c = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
    fn = pair_c.functions.mint(JOEY, JOEY)
    receipt, nonce = send_tx(w3, acct, fn, f"mint LP {sym}", nonce=nonce)
    log_tx(st, 3, f"mint_{sym}", receipt)

    st.setdefault("pairs", {})[sym] = {"address": pair_addr,
                                        "block": receipt["blockNumber"]}
    save_state(st)
    return nonce


def stage3(w3, acct, st, garbage_abi, dry_run):
    print("\n" + "=" * 60)
    print("  [STAGE 3] Create 13 LP pairs")
    print("=" * 60)

    garb_addr = st.get("garbage_address")
    if not garb_addr:
        if dry_run:
            print("  [DRY] No contract deployed -- printing plan:")
            for i, (sym, _, gw, pw, via) in enumerate(PAIRS, 1):
                method = "addLP" if via else "manual"
                print(f"    {i:2d}. GARBAGE/{sym:10s}  {gw:>12,} GARBAGE + "
                      f"{pw/1e18:>12.4f} {sym}  [{method}]")
            return
        raise RuntimeError("No garbage_address in state -- run stage 1 first")

    garbage = w3.eth.contract(address=garb_addr, abi=garbage_abi)
    nonce = w3.eth.get_transaction_count(acct.address)

    for i, (sym, partner, garb_whole, part_wei, via_addlp) in enumerate(PAIRS, 1):
        print(f"\n  --- Pair {i}/13: GARBAGE/{sym} ---")

        if sym in st.get("pairs", {}):
            print(f"    Already created at {st['pairs'][sym]['address']} -- skipping")
            continue

        if via_addlp:
            nonce = _create_pair_addlp(w3, acct, garbage, garb_addr, sym,
                                       partner, garb_whole, part_wei, nonce,
                                       st, dry_run)
        else:
            nonce = _create_pair_manual(w3, acct, garbage, garb_addr, sym,
                                        partner, garb_whole, part_wei, nonce,
                                        st, dry_run)

    created = len(st.get("pairs", {}))
    print(f"\n  [STAGE 3] {created}/13 pairs created")


# ═══════════════════════════════════════════════════════════════════════════
#  STAGE 4: LAUNCH TRADING
# ═══════════════════════════════════════════════════════════════════════════

def stage4(w3, acct, st, garbage_abi, dry_run):
    print("\n" + "=" * 60)
    print("  [STAGE 4] Launch trading")
    print("=" * 60)

    if st.get("launched"):
        print(f"  Already launched -- skipping")
        return

    garb_addr = st.get("garbage_address")
    if not garb_addr:
        if dry_run:
            print(f"  [DRY] Would call GARBAGE.launch()")
            return
        raise RuntimeError("No garbage_address")

    garbage = w3.eth.contract(address=garb_addr, abi=garbage_abi)

    # Check if already launched
    active = garbage.functions.tradingActiveTime().call()
    if active > 0:
        print(f"  Already live at block {active}")
        st["launched"] = True
        save_state(st)
        return

    fn = garbage.functions.launch()
    receipt, _ = send_tx(w3, acct, fn, "launch()", dry_run=dry_run)

    if not dry_run:
        active = garbage.functions.tradingActiveTime().call()
        print(f"  Trading live at block {active}")
        st["launched"] = True
        log_tx(st, 4, "launch", receipt)

    print(f"  [STAGE 4] Done")


# ═══════════════════════════════════════════════════════════════════════════
#  STAGE 5: BURN ALL LP TOKENS
# ═══════════════════════════════════════════════════════════════════════════

def stage5(w3, acct, st, dry_run):
    print("\n" + "=" * 60)
    print(f"  [STAGE 5] Burn LP tokens to {BURN}")
    print("=" * 60)

    pairs_done = st.get("pairs", {})
    if not pairs_done:
        if dry_run:
            print(f"  [DRY] Would burn LP tokens for all 13 pairs to {BURN}")
            return
        raise RuntimeError("No pairs in state")

    nonce = w3.eth.get_transaction_count(acct.address)
    burned = 0

    for sym, info in pairs_done.items():
        pair_addr = info["address"]
        print(f"\n  Burn GARBAGE/{sym} LP ({pair_addr[:10]}...)")

        # Check if already burned
        if sym in st.get("lp_burns", {}):
            print(f"    Already burned -- skipping")
            burned += 1
            continue

        pair_c = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
        lp_bal = pair_c.functions.balanceOf(JOEY).call()

        if lp_bal == 0:
            print(f"    Joey LP balance = 0 (already burned or never received)")
            st.setdefault("lp_burns", {})[sym] = {"amount": 0}
            save_state(st)
            burned += 1
            continue

        print(f"    LP balance: {lp_bal}")

        fn = pair_c.functions.transfer(BURN, lp_bal)
        receipt, nonce = send_tx(w3, acct, fn, f"burn LP {sym}",
                                 nonce=nonce, dry_run=dry_run)

        if not dry_run:
            # Verify (allow stale RPC — final check in stage 6)
            import time as _t; _t.sleep(2)
            remaining = pair_c.functions.balanceOf(JOEY).call()
            burn_bal  = pair_c.functions.balanceOf(BURN).call()
            if remaining > 0:
                print(f"    WARN: Joey still shows {remaining} LP (may be stale RPC)")
            print(f"    Burned {lp_bal} LP.  Burn addr balance: {burn_bal}")
            st.setdefault("lp_burns", {})[sym] = {"amount": str(lp_bal),
                                                    "tx": receipt["transactionHash"].hex()}
            log_tx(st, 5, f"burn_{sym}", receipt)
            burned += 1

    print(f"\n  [STAGE 5] {burned}/{len(pairs_done)} LP pairs burned")


# ═══════════════════════════════════════════════════════════════════════════
#  STAGE 6: VERIFY & PERSIST
# ═══════════════════════════════════════════════════════════════════════════

def stage6(w3, st, garbage_abi):
    print("\n" + "=" * 60)
    print("  [STAGE 6] Verification & persist")
    print("=" * 60)

    garb_addr = st.get("garbage_address")
    if not garb_addr:
        print("  No contract -- skipping verification")
        return

    garbage = w3.eth.contract(address=garb_addr, abi=garbage_abi)
    factory = w3.eth.contract(address=FACT_V2, abi=FACTORY_ABI)

    # 1) Check all pairs
    ok = 0
    receipt_pairs = {}
    for sym, partner, garb_whole, _, _ in PAIRS:
        pair_addr = factory.functions.getPair(garb_addr, partner).call()
        if pair_addr == ZERO_ADDR:
            print(f"  FAIL: GARBAGE/{sym} pair not found")
            continue

        pair_c = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
        r0, r1, _ = pair_c.functions.getReserves().call()
        lp_joey = pair_c.functions.balanceOf(JOEY).call()
        lp_burn = pair_c.functions.balanceOf(BURN).call()

        status = "OK" if r0 > 0 and r1 > 0 and lp_joey == 0 and lp_burn > 0 else "ISSUE"
        print(f"  {sym:10s}  pair={pair_addr[:12]}...  r0={r0}  r1={r1}  "
              f"joey_lp={lp_joey}  burn_lp={lp_burn}  [{status}]")

        receipt_pairs[sym] = {
            "pair": pair_addr,
            "reserve0": str(r0),
            "reserve1": str(r1),
            "joey_lp": str(lp_joey),
            "burn_lp": str(lp_burn),
        }
        if status == "OK":
            ok += 1

    print(f"\n  Pairs verified: {ok}/13")

    # 2) Token state
    supply  = garbage.functions.totalSupply().call()
    jbal    = garbage.functions.balanceOf(JOEY).call()
    active  = garbage.functions.tradingActiveTime().call()
    dist    = garbage.functions.distributor().call()
    pls_bal = w3.eth.get_balance(JOEY)

    expected_joey = 878_221_881 * G_FAC
    pct = jbal / supply * 100

    print(f"\n  GARBAGE totalSupply: {supply / G_FAC:,.0f}")
    print(f"  Joey balance:       {jbal / G_FAC:,.0f}  ({pct:.2f}%)")
    print(f"  tradingActiveTime:  {active}")
    print(f"  Distributor:        {dist}")
    print(f"  Joey PLS remaining: {pls_bal / 1e18:,.0f}")
    print(f"  100K floor check:   {'PASS' if pls_bal >= PLS_FLOOR else 'FAIL'}")

    # 3) Write deploy receipt
    receipt_data = {
        "garbage_address": garb_addr,
        "distributor_address": st.get("distributor_address"),
        "deploy_block": st.get("tx_log", [{}])[0].get("block") if st.get("tx_log") else None,
        "trading_active_block": active,
        "pairs": receipt_pairs,
        "joey_garbage_balance": str(jbal),
        "joey_pls_remaining": str(pls_bal),
        "total_txs": len(st.get("tx_log", [])),
        "timestamp": int(time.time()),
    }
    tmp = RECEIPT_F.with_suffix(".tmp")
    tmp.write_text(json.dumps(receipt_data, indent=2))
    os.replace(str(tmp), str(RECEIPT_F))
    print(f"\n  Receipt -> {RECEIPT_F.relative_to(REPO)}")

    # 4) Update contracts.json
    if CONTR_F.exists():
        contracts = json.loads(CONTR_F.read_text())
    else:
        contracts = {}
    contracts["GARBAGE"] = garb_addr
    contracts["GARBAGE_DISTRIBUTOR"] = st.get("distributor_address", "")
    tmp = CONTR_F.with_suffix(".tmp")
    tmp.write_text(json.dumps(contracts, indent=2))
    os.replace(str(tmp), str(CONTR_F))
    print(f"  contracts.json updated")

    # 5) Update .env
    env_file = REPO / ".env"
    env_lines = []
    if env_file.exists():
        env_lines = env_file.read_text().splitlines()

    def _set_env(lines, key, val):
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={val}"
                return lines
        lines.append(f"{key}={val}")
        return lines

    env_lines = _set_env(env_lines, "GARBAGE_ADDRESS", garb_addr)
    env_lines = _set_env(env_lines, "GARBAGE_DISTRIBUTOR", st.get("distributor_address", ""))
    tmp = env_file.with_suffix(".tmp")
    tmp.write_text("\n".join(env_lines) + "\n")
    os.replace(str(tmp), str(env_file))
    print(f"  .env updated")

    print(f"\n  [STAGE 6] Verification complete")


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Deploy GARBAGE pDAI Printer Token on PulseChain")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate everything, send nothing")
    parser.add_argument("--stage", type=int, default=0,
                        help="Resume from stage N (0-6)")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  GARBAGE pDAI Printer -- Deployment Script")
    print("  DaiHard fork | 10%% tax | 13 LP pairs | All LP burned")
    print("=" * 60)

    if args.dry_run:
        print("  MODE: DRY-RUN (simulate only, no transactions sent)")

    # Load .env (check repo, parent dir, and /opt/joystick)
    for envf in [REPO / ".env.pulse", REPO / ".env",
                 Path("/opt/joystick/.env.pulse"), Path("/opt/joystick/.env")]:
        if envf.exists():
            load_dotenv(envf)

    pkey = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
    if not pkey:
        print("ERROR: DYSNOMIA_PRIVATE_KEY not set")
        print("  Set via environment or .env file")
        sys.exit(1)

    acct = Account.from_key(pkey)
    if acct.address.lower() != JOEY.lower():
        print(f"ERROR: Key -> {acct.address}, expected {JOEY}")
        sys.exit(1)

    # Connect
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        print(f"ERROR: Cannot connect to {RPC_URL}")
        sys.exit(1)

    blk = w3.eth.block_number
    print(f"\n  RPC:   {RPC_URL}")
    print(f"  Block: {blk:,}")

    # Load state
    st = load_state()

    # Run stages
    start = args.stage

    try:
        if start <= 0:
            stage0(w3, acct)

        garbage_abi = None
        if start <= 1:
            addr, garbage_abi = stage1(w3, acct, st, args.dry_run)
        else:
            # Load ABI from file
            if ABI_F.exists():
                garbage_abi = json.loads(ABI_F.read_text())

        if start <= 2:
            stage2(w3, acct, st, args.dry_run)

        if start <= 3 and garbage_abi:
            stage3(w3, acct, st, garbage_abi, args.dry_run)

        if start <= 4 and garbage_abi:
            stage4(w3, acct, st, garbage_abi, args.dry_run)

        if start <= 5:
            stage5(w3, acct, st, args.dry_run)

        if start <= 6 and garbage_abi and not args.dry_run:
            stage6(w3, st, garbage_abi)

    except RuntimeError as e:
        print(f"\n  ABORT: {e}")
        print(f"  State saved. Resume with: --stage N")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n  Interrupted. State saved. Resume with: --stage N")
        sys.exit(1)

    # Final summary
    garb_addr = st.get("garbage_address", "N/A")
    dist_addr = st.get("distributor_address", "N/A")
    n_pairs   = len(st.get("pairs", {}))
    n_burns   = len(st.get("lp_burns", {}))
    n_txs     = len(st.get("tx_log", []))

    print("\n" + "=" * 60)
    print("  DEPLOYMENT SUMMARY")
    print("=" * 60)
    print(f"  GARBAGE:      {garb_addr}")
    print(f"  Distributor:  {dist_addr}")
    print(f"  Pairs:        {n_pairs}/13 created")
    print(f"  LP burns:     {n_burns}/{n_pairs} burned")
    print(f"  Total TXs:    {n_txs}")
    if not args.dry_run:
        pls = w3.eth.get_balance(JOEY) / 1e18
        print(f"  Joey PLS:     {pls:,.0f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
