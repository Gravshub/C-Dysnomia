"""
JOYSTICK Mission Control — Configuration
All addresses, RPCs, and constants for the read-only dashboard API.
Mirrors the bot's .env.pulse pattern. No private keys needed here.
"""

import os

# ─── RPC ─────────────────────────────────────────────────────────────
# Dual-RPC pattern: g4mm4 for reads (faster), pulsechain.com fallback
RPC_READ = os.getenv("RPC_URL_READ", "https://rpc-pulsechain.g4mm4.io")
RPC_FALLBACK = os.getenv("RPC_URL", "https://rpc.pulsechain.com")
CHAIN_ID = 369

# ─── Core addresses ──────────────────────────────────────────────────
JOEY_WALLET = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
TGSV8 = "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32"
TGSV8PLUS = os.getenv("TGSV8PLUS_ADDRESS", "0xA5D7771f16204d26770657eac186A6167e69e736")
JV8A = "0x364793Ea48DEe0b5484F98235ABd1B5f996A0C30"
GIBS_LAU = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"
DSS = "0x91Df693177eE5C81016d0B7c4c2052A7d229c031"

# ─── Multi-wallet addresses (for auth checks) ─────────────────────
MINTER_WALLET = os.getenv("MINTER_WALLET", "0x924C0E0900eCA99D3bfA96D2E02B65f2c5F3e11a")
SELLER_WALLET = os.getenv("SELLER_WALLET", "0xf8D37fBe8682676Ad21C09e907d48bFB4DaAb1d8")

# ─── Token addresses (for balance reads) ─────────────────────────────
WPLS = "0xA1077a294dDE1B09bB078844df40758a5D0f9a27"
AFFECTION = "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D"
MV_TOKEN = "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29"  # WM
ATROPA = "0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6"
VOID = "0x965B0d74591bF30327075A247C47dBf487dCff08"
FED = "0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff"

# Token registry: symbol → address
# Used by chain_reader for batched balanceOf calls
TOKEN_REGISTRY = {
    "PLS":       None,  # native — use eth_getBalance
    "GIBS":      GIBS_LAU,
    "AFFECTION": AFFECTION,
    "WM":        MV_TOKEN,
    "ATROPA":    ATROPA,
    "VOID":      VOID,
    "FED":       FED,
    "WPLS":      WPLS,
}

# ─── DEX ─────────────────────────────────────────────────────────────
PULSEX_V1_FACTORY = "0x1715a3E4A142d8b698131108995174F37aEBA10D"
PULSEX_V2_FACTORY = "0x29eA7545DEf87022BAdc76323F373EA1e707C523"
PULSEX_V1_ROUTER = "0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02"
PULSEX_V2_ROUTER = "0x165C3410fC91EF562C50559f7d2289fEbed552d9"
GIBS_WPLS_PAIR = "0x7bca1c997c..."  # TODO: full address once confirmed

# ─── TGSv8 expected reference addresses ────────────────────────────
TGSV8_EXPECTED_REFS = {
    "minter_v4": "0x394c3D5990cEfC7Be36B82FDB07a7251ACe61cc7",
    "minter_v3": "0x0c4F73328dFCECfbecf235C9F78A4494a7EC5ddC",
    "mv":        "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29",
    "router_v1": "0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02",
    "router_v2": "0x165C3410fC91EF562C50559f7d2289fEbed552d9",
}
# ─── TGSv8+ expected reference addresses ──────────────────────────
TGSV8PLUS_EXPECTED_REFS = {
    "lau":        "0x66a08aa12da955eb63d7ac121a88b2b210a07b03",
    "pay_token":  "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D",
    "wpls":       "0xA1077a294dDE1B09bB078844df40758a5D0f9a27",
    "router_v1":  "0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02",
    "router_v2":  "0x165C3410fC91EF562C50559f7d2289fEbed552d9",
    "factory_v1": "0x1715a3E4A142d8b698131108995174F37aEBA10D",
    "factory_v2": "0x29eA7545DEf87022BAdc76323F373EA1e707C523",
}

# ─── AFFECTION BuyWith payment tokens ─────────────────────────────
AFF_MATH  = "0xB680F0cc810317933F234f67EB6A9E923407f05D"   # MATH v1.1
AFF_PI    = "0xA2262D7728C689526693aE893D0fD8a352C7073C"   # pINDEPENDENCE
AFF_G5    = "0x2fc636E7fDF9f3E8d61033103052079781a6e7D2"   # GIMME FIVE
AFF_FA    = "0x232a27AB6941281b3f474Fe5fF7Cc89816fB675A"   # libConjecture v1.0
AFF_FAUNG = "0x73A19FaFb359faf519C9707b781dfdB88407d10d"   # libDynamic v1.0

# Per-AFF payment requirement (from contract rates)
# multiBuyWith: 1 loop = 3 AFF.  Cost per loop in payment token wei:
#   MATH=3, PI=0.01, G5=0.6, Fa=12, Faung=6
# ⇒ Cost per 1 AFF:
AFF_ROUTES = [
    {"name": "MATH",  "addr": AFF_MATH,  "per_aff": 1.0},       # 1 MATH / AFF
    {"name": "PI",    "addr": AFF_PI,    "per_aff": 0.003333},   # ~0.00333 PI / AFF
    {"name": "G5",    "addr": AFF_G5,    "per_aff": 0.2},        # 0.2 G5 / AFF
    {"name": "Fa",    "addr": AFF_FA,    "per_aff": 4.0},        # 4 Fa / AFF
    {"name": "Faung", "addr": AFF_FAUNG, "per_aff": 2.0},        # 2 Faung / AFF
]

# WM mint gas estimate (from token_factory.py defaults)
WM_MINT_GAS_PER_TOKEN = 130_000   # gas units per WM minted
# AFF multiBuyWith gas estimate (base + per-loop overhead + swap overhead)
AFF_BUYWITH_GAS_BASE = 4_200_000  # base gas for 1 loop of multiBuyWith
AFF_SWAP_OVERHEAD     = 200_000   # approvals + token swap

# ─── Stablecoins for PLS/USD pricing ──────────────────────────────
DAI = "0x6B175474E89094C44Da98b954EedeAC495271d0F"    # pDAI (18 decimals)
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"  # pUSDC (6 decimals)

# ─── Multi-wallet portfolio tracking ──────────────────────────────
PORTFOLIO_WALLETS = {
    "Joey":   JOEY_WALLET,
    "Minter": MINTER_WALLET,
    "Seller": SELLER_WALLET,
    "TGSv8":  TGSV8,
}

# ─── Infrastructure ──────────────────────────────────────────────────
MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"

# ─── Validator target ────────────────────────────────────────────────
VALIDATOR_TARGET_PLS = 32_000_000  # 32M PLS

# ─── Gas ─────────────────────────────────────────────────────────────
GAS_BUFFER_FLOOR = 100_000  # 100K PLS minimum buffer
GAS_CEILING_BEATS = int(os.getenv("GAS_CEILING_BEATS", "50").replace(",", ""))

# ─── Engine definitions ─────────────────────────────────────────────
# Static metadata for each engine — runtime state comes from chain/bot
ENGINES = [
    {
        "id": "E1", "name": "RAZOR", "type": "Cross-DEX arb",
        "contract_fn": "atomicArb()",
        "description": "Cross-DEX QING arbitrage via atomicArb()",
    },
    {
        "id": "E2", "name": "CEREAL", "type": "DSS",
        "contract_fn": "chatAndClaim()",
        "description": "chatAndClaim → GIBS → PLS",
    },
    {
        "id": "E3", "name": "MERIDIAN", "type": "Beat/Dione",
        "contract_fn": "CHEON.Su() + META.Beat()",
        "description": "Territory positioning (CHEON.Su + META.Beat)",
    },
    {
        "id": "E4", "name": "FACTORY", "type": "AFF + WM mint",
        "contract_fn": "mintWM() / multiGenerate()",
        "description": "Dual-mode token factory: AFF generate + WM mint",
    },
    {
        "id": "E5", "name": "ABUPRU", "type": "LAU loop",
        "contract_fn": "EmitSniper",
        "description": "Mathematical state loop + EmitSniper",
    },
    {
        "id": "E6", "name": "DaVINCI", "type": "Treasury sniper",
        "contract_fn": "batchClaimTreasury()",
        "description": "Treasury sweep via recon data",
    },
    {
        "id": "E7", "name": "BACKBONE", "type": "Spine runner",
        "contract_fn": "batchMintAndClaim()",
        "description": "Debenture=True V2 mint-claim loops",
    },
    {
        "id": "E8", "name": "PHR3AK", "type": "Deploy/Arm/Stitch",
        "contract_fn": "executeRoute()",
        "description": "V4 node deploy, Debenture token acquisition, LP edge creation",
    },
]

# ─── Dashboard server ────────────────────────────────────────────────
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8369"))  # 369 = PulseChain :)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")

# ─── Polling ─────────────────────────────────────────────────────────
# How often the dashboard frontend should poll (hint to client)
POLL_INTERVAL_SEC = 15

# ─── Bot state file paths (read by API if bot is running) ────────────
# These are relative to the bot's data directory
BOT_DATA_DIR = os.getenv("BOT_DATA_DIR", "")
ENGINE_STATE_FILE = os.path.join(BOT_DATA_DIR, "engine_state.json") if BOT_DATA_DIR else ""
TX_LOG_FILE = os.path.join(BOT_DATA_DIR, "tx_log.json") if BOT_DATA_DIR else ""

# ─── Balance history ──────────────────────────────────────────────
HISTORY_DIR = os.path.join(os.path.dirname(__file__), "data")
HISTORY_FILE = os.path.join(HISTORY_DIR, "balance_history.json")
HISTORY_RECORD_INTERVAL = 900   # 15 minutes
HISTORY_MAX_AGE = 604800        # 7 days (1 week)

# ─── VOID COMMS (chat) ───────────────────────────────────────────
FOMALHAUTE = "0x7aE73C498A308247BE73688c09c96B3fd06dDB84"  # ZHOU SHIO — log storage
SEI = "0x3dC54d46e030C42979f33C9992348a990acb6067"         # player management
ZHOU = "0x5cc318d0c01fed5942b5ed2f53db07727d36e261"
COMMS_POLL_SEC = 30             # frontend polls comms every 30s
COMMS_CACHE_TTL = 30            # server-side cache TTL (seconds)
COMMS_CHUNK_SIZE = 5000         # max block range per eth_getLogs call
BLOCKS_PER_DAY = 8640           # ~10s blocks on PulseChain
