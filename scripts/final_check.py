#!/usr/bin/env python3
"""Final checks: verify SEI, validate CHAN.Yan, check gas estimate for SEI.Start()."""
from web3 import Web3
from eth_utils import keccak

RPC = "https://rpc.pulsechainstats.com"
w3 = Web3(Web3.HTTPProvider(RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

SEI_ADDR    = Web3.to_checksum_address("0x3dC54d46e030C42979f33C9992348a990acb6067")
CHAN_ADDR   = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
MAP_ADDR    = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
GIBS_ADDR   = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
NOUMENON_WALLET = Web3.to_checksum_address("0xEbE9B8673d7096DCEE26DA7d9eaf6fc4eBe30980")
NOUMENON_YUE = Web3.to_checksum_address("0x935a694377CF48d8FC934F17dB289774f0Ce7075")

def addr_call(addr, fn):
    abi = [{"inputs":[],"name":fn,"outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        r = getattr(c.functions, fn)().call()
        return r
    except Exception as e:
        return f"ERR: {e}"

def string_call(addr, fn):
    abi = [{"inputs":[],"name":fn,"outputs":[{"type":"string"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        return getattr(c.functions, fn)().call()
    except:
        return None

def uint256_call(addr, fn):
    abi = [{"inputs":[],"name":fn,"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        return getattr(c.functions, fn)().call()
    except:
        return None

def addr_call_addr(addr, fn, input_addr):
    abi = [{"inputs":[{"type":"address"}],"name":fn,"outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        r = getattr(c.functions, fn)(input_addr).call()
        return r
    except Exception as e:
        return f"ERR: {e}"

# ─── VERIFY SEI ───────────────────────────────────────────────────────────────
print(f"\n=== SEI VERIFICATION: {SEI_ADDR} ===")
print(f"  name         = {string_call(SEI_ADDR, 'name')}")
print(f"  symbol       = {string_call(SEI_ADDR, 'symbol')}")
print(f"  totalSupply  = {uint256_call(SEI_ADDR, 'totalSupply')}")
ms = uint256_call(SEI_ADDR, 'maxSupply')
ts = uint256_call(SEI_ADDR, 'totalSupply')
if ms and ts:
    print(f"  maxSupply    = {ms/1e18:.2f}")
    print(f"  minted %     = {ts/ms*100:.2f}%")
    print(f"  to mint      = {(ms-ts)/1e18:.2f} remaining")
chan = addr_call(SEI_ADDR, 'Chan')
print(f"  Chan()       = {chan}")
print(f"  Chan==CHAN?  = {chan.lower() == CHAN_ADDR.lower()}")
print(f"  code size    = {len(w3.eth.get_code(SEI_ADDR))} bytes")

# Check Start() function selector
start_sel = keccak(text="Start(address,string,string)")[:4]
sei_code = w3.eth.get_code(SEI_ADDR).hex()
print(f"  has Start()? = {'0x'+start_sel.hex() in sei_code}")

# ─── VALIDATE CHAN.YAN FOR NOUMENON ─────────────────────────────────────────
print(f"\n=== CHAN.YAN() VALIDATION ===")
yan_noumenon = addr_call_addr(CHAN_ADDR, "Yan", NOUMENON_WALLET)
print(f"  CHAN.Yan(Noumenon wallet) = {yan_noumenon}")
print(f"  Expected YUE             = {NOUMENON_YUE}")
if isinstance(yan_noumenon, str) and not yan_noumenon.startswith("ERR"):
    print(f"  Match? {yan_noumenon.lower() == NOUMENON_YUE.lower()}")

# ─── GAS ESTIMATE FOR SEI.START() ────────────────────────────────────────────
print(f"\n=== GAS ESTIMATE: SEI.Start() ===")
start_abi = [{
    "inputs": [
        {"name":"LauToken","type":"address"},
        {"name":"YueName","type":"string"},
        {"name":"YueSymbol","type":"string"}
    ],
    "name": "Start",
    "outputs": [
        {"name":"Yue","type":"address"},
        {"name":"UserToken","type":"address"}
    ],
    "stateMutability": "nonpayable",
    "type": "function"
}]
sei_contract = w3.eth.contract(address=SEI_ADDR, abi=start_abi)
try:
    gas_est = sei_contract.functions.Start(
        GIBS_ADDR,
        "Gibson Wallet",
        "GIBSw"
    ).estimate_gas({'from': JOEY_WALLET})
    gas_price = w3.eth.gas_price
    cost_pls  = gas_est * gas_price / 1e18
    print(f"  Gas estimate : {gas_est:,} gas units")
    print(f"  Gas price    : {gas_price/1e9:.2f} Gwei")
    print(f"  Estimated PLS cost: {cost_pls:.6f} PLS")
except Exception as e:
    print(f"  Error estimating: {e}")
    # Try a simulation
    try:
        result = sei_contract.functions.Start(
            GIBS_ADDR,
            "Gibson Wallet",
            "GIBSw"
        ).call({'from': JOEY_WALLET})
        print(f"  Simulation result: YUE={result[0]}  LAU={result[1]}")
    except Exception as e2:
        print(f"  Simulation also failed: {e2}")

# ─── GAS ESTIMATE FOR MAP.NEW(GIBS) ──────────────────────────────────────────
print(f"\n=== GAS ESTIMATE: MAP.New(GIBS) ===")
new_abi = [{
    "inputs": [{"name":"Integrative","type":"address"}],
    "name": "New",
    "outputs": [{"name":"Mu","type":"address"}],
    "stateMutability": "nonpayable",
    "type": "function"
}]
map_contract = w3.eth.contract(address=MAP_ADDR, abi=new_abi)
try:
    gas_est2 = map_contract.functions.New(GIBS_ADDR).estimate_gas({'from': JOEY_WALLET})
    gas_price = w3.eth.gas_price
    cost_pls2 = gas_est2 * gas_price / 1e18
    print(f"  Gas estimate : {gas_est2:,} gas units")
    print(f"  Gas price    : {gas_price/1e9:.2f} Gwei")
    print(f"  Estimated PLS cost: {cost_pls2:.6f} PLS")
except Exception as e:
    print(f"  Error estimating: {e}")
    try:
        result2 = map_contract.functions.New(GIBS_ADDR).call({'from': JOEY_WALLET})
        print(f"  Simulation result QING: {result2}")
    except Exception as e2:
        print(f"  Simulation also failed: {e2}")

# ─── COMPLETE ADDRESS TABLE ────────────────────────────────────────────────────
print(f"\n=== COMPLETE VERIFIED ADDRESS TABLE ===")
contracts = {
    "GIBS (Joey LAU)":   "0x66a08aa12da955eb63d7ac121a88b2b210a07b03",
    "DSS":               "0x91Df693177eE5C81016d0B7c4c2052A7d229c031",
    "VOID":              "0x965B0d74591bF30327075A247C47dBf487dCff08",
    "ZHOU":              "0x5cc318d0c01fed5942b5ed2f53db07727d36e261",
    "YANG":              "0xb702b3ec6d9de1011be963efe30a28b6ddfbe011",
    "YAU":               "0x7e91d862a346659daeed93726e733c8c1347a225",
    "ZHENG":             "0x24e62c39e34d7fe2b7df1162e1344eb6eb3b3e15",
    "SIU":               "0x43136735603d4060f226c279613a4dd97146937c",
    "AFFECTION":         "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D",
    "WM (MV)":           "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29",
    "CROWS":             "0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1",
    # Newly discovered:
    "CHAN":              "0xe250bf9729076B14A8399794B61C72d0F4AeFcd8",
    "XIE (Fornax)":      "0x4Df51741F2926525A21bF63E4769bA70633D2792",
    "XIA":               "0x7f4a4DD4a6f233d2D82BE38b2F9fc0Fef46f25FA",
    "MAI":               "0xc48B0a4E79eF302c8Eb5be71F562d08fB8E6A3d8",
    "QI":                "0x4d9Ce396BE95dbc5F71808c38107eB7422FD9a03",
    "ZUO (QING)":        "0xb0Ba7D36B7F0505879179ecE7401F24eB653c6E1",
    "CHO":               "0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB",
    "SEI":               "0x3dC54d46e030C42979f33C9992348a990acb6067",
    "MAP":               "0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75",
    "HECKE":             "0x29A924D9B0233026B9844f2aFeB202F1791D7593",
    "Math lib":          "0xB680F0cc810317933F234f67EB6A9E923407f05D",
}
for name, addr in contracts.items():
    cs_addr = Web3.to_checksum_address(addr)
    code_size = len(w3.eth.get_code(cs_addr))
    print(f"  {name:20s} {cs_addr}  [{code_size:6d} bytes]")
