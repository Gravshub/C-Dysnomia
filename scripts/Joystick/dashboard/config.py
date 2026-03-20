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

# ─── Infrastructure ──────────────────────────────────────────────────
MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"

# ─── Validator target ────────────────────────────────────────────────
VALIDATOR_TARGET_PLS = 32_000_000  # 32M PLS

# ─── Gas ─────────────────────────────────────────────────────────────
GAS_BUFFER_FLOOR = 100_000  # 100K PLS minimum buffer
GAS_CEILING_BEATS = int(os.getenv("GAS_CEILING_BEATS", "50"))

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
HISTORY_MAX_AGE = 86400         # 24 hours
