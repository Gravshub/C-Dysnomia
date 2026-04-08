"""
config.py — Single source of truth for all addresses, thresholds, and env vars.
No magic strings anywhere else in Joystick. Import from here.
"""
import os
from decimal import Decimal
from web3 import Web3

# ── RPC ──────────────────────────────────────────────────────────────────────
CHAIN_ID = 369

# Legacy env vars — RPCPool reads them directly in rpc_provider.py.
# Kept here for backward compat with standalone scripts that import config.
SUBMIT_RPC = os.getenv("PULSECHAIN_RPC", "https://rpc.pulsechain.com")
READ_RPC   = os.getenv("PULSECHAIN_READ_RPC", "https://rpc-pulsechain.g4mm4.io")

# RPC tuning (env-overridable)
RPC_READ_TIMEOUT   = int(os.getenv("RPC_READ_TIMEOUT", "30"))
RPC_SUBMIT_TIMEOUT = int(os.getenv("RPC_SUBMIT_TIMEOUT", "60"))
RPC_MAX_RETRIES    = int(os.getenv("RPC_MAX_RETRIES", "2"))
RPC_CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("RPC_CB_THRESHOLD", "5"))
RPC_COOLDOWN_BASE  = int(os.getenv("RPC_COOLDOWN_BASE", "30"))

# ── Player ────────────────────────────────────────────────────────────────────
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

# ── Core tokens ───────────────────────────────────────────────────────────────
AFFECTION  = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
WM         = Web3.to_checksum_address("0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29")
WPLS       = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
PDAI       = Web3.to_checksum_address("0x6B175474E89094C44Da98b954EedeAC495271d0F")
PUSDC      = Web3.to_checksum_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")

# ── Joey's contracts ──────────────────────────────────────────────────────────
GIBS_LAU   = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
GIBS_QING  = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
JOEY_YUE   = Web3.to_checksum_address("0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0")
# ── DSS (DysnomiaSelfSnipev4) ────────────────────────────────────────────
# STATUS: DEPRECATED FOR MINTING (as of TGSv8+ deployment, March 2026)
#
# All minting revenue now flows through TGSv8+ via harvestCycle(), which is
# silent (no Chat), atomic (1 TX), and includes automatic LP creation + burn.
#
# DSS is KEPT for one purpose only: broadcasting messages to the VOID chat.
# Joey can still call DSS.chat(text) to post to the VOID when desired.
#
# To broadcast to VOID:  python scripts/tx_void_broadcast.py
DSS        = Web3.to_checksum_address("0x91Df693177eE5C81016d0B7c4c2052A7d229c031")

# GIBS QING waat — constant identifier for territory computation
GIBS_QING_WAAT = 251913148994206487765525643443518492465195287520927385378321984475167864513

# ── Game contracts ────────────────────────────────────────────────────────────
META       = Web3.to_checksum_address("0xE77Bdae31b2219e032178d88504Cc0170a5b9B97")
CHEON      = Web3.to_checksum_address("0x3d23084cA3F40465553797b5138CFC456E61FB5D")
VOID       = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")
MAP_ADDR   = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
CHOA       = Web3.to_checksum_address("0x0f5a352fd4cA4850c2099C15B3600ff085B66197")
ENTEH_QING = Web3.to_checksum_address("0xA43F71ac277022A547c56706fbBc5d93f88C3467")

# ── SHIO tokens (Beat prerequisites) ─────────────────────────────────────────
FORNAX     = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
FOMALHAUTE = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")
CHO        = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")

# ── Key ecosystem tokens ─────────────────────────────────────────────────────
FED = Web3.to_checksum_address("0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff")

# ── Atropa ecosystem tokens (pDAI routes) ────────────────────────────────────
PINDEPENDENCE = Web3.to_checksum_address("0xA2262D7728C689526693aE893D0fD8a352C7073C")
GIMME_FIVE    = Web3.to_checksum_address("0x2fc636E7fDF9f3E8d61033103052079781a6e7D2")
MATH_V11      = Web3.to_checksum_address("0xB680F0cc810317933F234f67EB6A9E923407f05D")
RNG           = Web3.to_checksum_address("0xa96BcbeD7F01de6CEEd14fC86d90F21a36dE2143")

# Seeded known LAU tokens (arb scanner starting list)
SEED_LAUS = [
    ("GIBS (Joey)",   GIBS_LAU),
    ("GIBS-orphan",   Web3.to_checksum_address("0xabf97a71dfd71f3763c86080693c1ec94e5de846")),
    ("enteh",         Web3.to_checksum_address("0xccE83CfF8B531EaDdcf11AB414C59DC046D1aAc7")),
    ("Grav LAU",      Web3.to_checksum_address("0xF462A6fc9a07c4f4bd03a54e03a5db3024d64D47")),
    ("pINDEPENDENCE", PINDEPENDENCE),
    ("GIMME FIVE",    GIMME_FIVE),
    ("MATH v1.1",     MATH_V11),
    ("RNG",           RNG),
]

# ── DEX ───────────────────────────────────────────────────────────────────────
PULSEX_V1_ROUTER  = Web3.to_checksum_address("0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02")
PULSEX_V1_FACTORY = Web3.to_checksum_address("0x1715a3E4A142d8b698131108995174F37aEBA10D")
PULSEX_V2_ROUTER  = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")
PULSEX_V2_FACTORY = Web3.to_checksum_address("0x29eA7545DEf87022BAdc76323F373EA1e707C523")
NINEMM_FACTORY    = Web3.to_checksum_address("0xE26E7F6b5A43A667dBA42Cd9C829d5C75A8093b1")
NINEINCH_FACTORY  = Web3.to_checksum_address("0x7a8FC9dEA0B3316b76686F2Cf58E1b3c02890F8D")

# ── Burn address (verified EOA, 158B PLS already burned) ─────────────────────
BURN_ADDRESS = Web3.to_checksum_address("0x0000000000000000000000000000000000000369")

# ── Infrastructure ────────────────────────────────────────────────────────────
MULTICALL3 = Web3.to_checksum_address("0xcA11bde05977b3631167028862bE2a173976CA11")

# TGSv8 — Active execution layer (Token Factory + WM Minting + Dual DEX)
# Supersedes TGSv5 (WM-only) and TGSv7 (no mintWM). See data/events/tgs_deprecation_log.json.
# TGSv8 deployed at block 25,943,194 — owner=Joey, active execution substrate
TGSV8 = Web3.to_checksum_address(
    os.getenv("TGSV8_ADDRESS", "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32")
)

# ── TGSv8+ — Companion contract for daily harvest pipeline ──────────────
# Handles: silent minting, atomic harvestCycle, LP burns, removeLiquidity,
# spread selling, generic execute. Deployed alongside TGSv8 (not a replacement).
TGSV8PLUS = os.getenv("TGSV8PLUS_ADDRESS", "")

# JoystickHub (modular proxy for harvest + AFF acquisition + Purchase arb)
# Deployed at block 26,092,219 — owner=Joey, modules: Harvest, Affection, Purchase
JOYSTICK_HUB = os.getenv(
    "JOYSTICK_HUB_ADDRESS", "0x7bd76A0f7e03A3BA76A621ba0988C7db0AdbAB14"
)
if JOYSTICK_HUB:
    JOYSTICK_HUB = Web3.to_checksum_address(JOYSTICK_HUB)

# HarvestModuleV2 — primeGibs calls mintToCap() instead of Generate()
# Deployed block 26,149,418. Replaces V1 at 0xFAFB227DdC0804A55677A23eE2Ca0E966452D3B2.
HARVEST_MODULE_V2 = Web3.to_checksum_address("0x400D052FAf0f46D3d5140a8F7246B69954539424")

# HarvestModuleV3 — atomic primeAndSell (anti-sniper)
# Deployed block 26,182,431. Registered at block 26,182,499.
# Closes sniper exploit: mintToCap + Purchase + sell in one atomic TX.
HARVEST_MODULE_V3 = Web3.to_checksum_address("0x281286b7c338fF570B1Cbf4911b3FA23353A3c02")

# FloorHarvestModule — atomic prime→LP→sell via direct pair.mint/swap (no router)
# PulseX V2 pair.mint(to, feeTo), mintToCap() × N, Purchase in wei
FLOOR_HARVEST_MODULE = Web3.to_checksum_address("0xF3Be3a9Ae911EEA2Ad5C07a74069f30AADAc8669")

AFFECTION_MODULE  = Web3.to_checksum_address("0xfb7C1A1Ef0Ce8AB527998a1c2Ca12C6CA400da4B")
PURCHASE_MODULE   = Web3.to_checksum_address("0xc59cb7229872E72B7349Ef7DFa170A2444a8264E")

# ── GIBS LP Pairs ────────────────────────────────────────────────────────────
GIBS_WPLS_V2_PAIR = Web3.to_checksum_address("0x7BCa1c997c475eac9c61417e88bed158ACA757f0")

# ── E2 Harvest Cycle Configuration ──────────────────────────────────────
# All values in basis points (0-10000). Override via env vars.
# Default strategy: 45% sell for PLS, 55% re-LP, burn 90% of new LP tokens.
HARVEST_SELL_BPS   = int(os.getenv("HARVEST_SELL_BPS", "4500"))    # 45% sold → PLS to wallet
HARVEST_BURN_BPS   = int(os.getenv("HARVEST_BURN_BPS", "9000"))    # 90% of LP → burned (permanent floor)
HARVEST_MINT_COUNT = int(os.getenv("HARVEST_MINT_COUNT", "17"))    # LAU minted per cycle (17 Purchase calls)
HARVEST_SELL_DEX   = int(os.getenv("HARVEST_SELL_DEX", "1"))       # 0=V1, 1=V2 for sell step
HARVEST_LP_DEX     = int(os.getenv("HARVEST_LP_DEX", "1"))         # 0=V1, 1=V2 for addLiquidity step
HARVEST_USE_SAFE   = os.getenv("HARVEST_USE_SAFE", "true").lower() == "true"  # safeMint required — silentMint fails when LAU self-balance=0

# V4/V3 Personal/Index minters
V4_MINTER = Web3.to_checksum_address("0x394c3D5990cEfC7Be36B82FDB07a7251ACe61cc7")
V3_MINTER = Web3.to_checksum_address("0x0c4F73328dFCECfbecf235C9F78A4494a7EC5ddC")

# ── Multi-mint contracts (Helios) ────────────────────────────────────────
MULTI_AFFECTION = Web3.to_checksum_address("0xCF138a83D739eE98D7A54159E94e5BFaa4B61988")

# ── AFFECTION BuyWith payment tokens ─────────────────────────────────────
AFF_G5    = Web3.to_checksum_address("0x2fc636E7fDF9f3E8d61033103052079781a6e7D2")  # GIMME FIVE
AFF_PI    = Web3.to_checksum_address("0xA2262D7728C689526693aE893D0fD8a352C7073C")  # pINDEPENDENCE
AFF_MATH  = Web3.to_checksum_address("0xB680F0cc810317933F234f67EB6A9E923407f05D")  # MATH v1.1
AFF_FA    = Web3.to_checksum_address("0x232a27AB6941281b3f474Fe5fF7Cc89816fB675A")  # libConjecture
AFF_FAUNG = Web3.to_checksum_address("0x73A19FaFb359faf519C9707b781dfdB88407d10d")  # libDynamic

# ── Hub tokens for pair discovery (Tier 1 scan) ─────────────────────────────
HUB_TOKENS = [
    WPLS,
    AFFECTION,
    Web3.to_checksum_address("0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff"),  # FED
    Web3.to_checksum_address("0x463413c579D29c26D59a65312657DFCe30D545A1"),  # TBILL
    GIBS_LAU,                                                                 # GIBS
    Web3.to_checksum_address("0x812571A12330A74E2A3C1fF8953f6f3aac7a83e9"),  # FDIC
    Web3.to_checksum_address("0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6"),  # ATROPA
    Web3.to_checksum_address("0x6B175474E89094C44Da98b954EedeAC495271d0F"),  # pDAI
]

# ── PulseX dual-DEX token list filters ────────────────────────────────────────
PULSEX_MIN_SPREAD_BPS = float(os.getenv("PULSEX_MIN_SPREAD_BPS", "0"))
PULSEX_MIN_TVL_PLS    = float(os.getenv("PULSEX_MIN_TVL_PLS", "1000"))

# ── Cross-DEX arb parameters ────────────────────────────────────────────────
CROSS_DEX_MIN_PROFIT_PLS = int(os.getenv("CROSS_DEX_MIN_PROFIT_PLS", "7000"))
CROSS_DEX_MIN_TVL_PLS    = int(os.getenv("CROSS_DEX_MIN_TVL_PLS", "50000"))
TGS_WPLS_BUFFER_PLS      = int(os.getenv("TGS_WPLS_BUFFER_PLS", "10000"))

# ── Graph arb parameters ────────────────────────────────────────────────────
GRAPH_ARB_MIN_PROFIT_PLS = int(os.getenv("GRAPH_ARB_MIN_PROFIT_PLS", "1000"))
GRAPH_ARB_MAX_IMPACT_PCT = float(os.getenv("GRAPH_ARB_MAX_IMPACT_PCT", "10.0"))
GRAPH_ARB_MAX_HOPS       = int(os.getenv("GRAPH_ARB_MAX_HOPS", "3"))
GRAPH_CACHE_TTL          = int(os.getenv("GRAPH_CACHE_TTL", "300"))    # 5 min pair registry
RESERVE_CACHE_TTL        = int(os.getenv("RESERVE_CACHE_TTL", "30"))   # 30 sec reserves

# PAIR_GRAPH_CACHE_PATH — If set, load pair registry from this path (bypasses TTL)
#   Useful for pre-cached data generated by manual `pair_discovery.py --force` runs
PAIR_GRAPH_CACHE_PATH = os.getenv("PAIR_GRAPH_CACHE_PATH", "")

# ── Multi-wallet ──────────────────────────────────────────────────────────────
MINTER_WALLET = os.getenv("MINTER_WALLET", "")
SELLER_WALLET = os.getenv("SELLER_WALLET", "")
if MINTER_WALLET:
    MINTER_WALLET = Web3.to_checksum_address(MINTER_WALLET)
if SELLER_WALLET:
    SELLER_WALLET = Web3.to_checksum_address(SELLER_WALLET)

MINTER_GAS_FLOOR = int(os.getenv("MINTER_GAS_FLOOR", "30000")) * 10**18
SELLER_GAS_FLOOR = int(os.getenv("SELLER_GAS_FLOOR", "30000")) * 10**18
SWEEP_THRESHOLD  = int(os.getenv("SWEEP_THRESHOLD", "500000")) * 10**18

# ── Thresholds (all env-overridable) ─────────────────────────────────────────
# PLS buffer — never operate below this
PLS_GAS_FLOOR  = int(os.getenv("PLS_GAS_FLOOR",  "100000")) * 10**18
# Target PLS level after emergency refill
PLS_REPLENISH  = int(os.getenv("PLS_REPLENISH",  "200000")) * 10**18
# Fraction of profit kept as PLS (gas reserve + validator fund)
PROFIT_SPLIT   = float(os.getenv("PROFIT_SPLIT",  "0.25"))
# Gas price ceiling in Beats — skip cycle if exceeded
# PulseChain gas is typically 500K-1M Beats (PLS is very cheap ~$0.00001)
GAS_PRICE_CEIL = int(os.getenv("GAS_PRICE_CEIL",  "3000000")) * 10**9
# DEX slippage tolerance
MAX_SLIPPAGE   = float(os.getenv("MAX_SLIPPAGE",  "0.02"))
# Gas estimate multiplier (safety buffer)
GAS_MULT       = float(os.getenv("GAS_MULT",      "2.5"))
# Gas pricing — PulseChain has no MEV, floor+epsilon is sufficient
# BOT3 proves 811K Beats works (~8% above floor of ~748K Beats)
GAS_PRICE_FLOOR_MULT = float(os.getenv("GAS_PRICE_FLOOR_MULT", "1.12"))  # 12% above base
GAS_PRIORITY_FEE     = int(os.getenv("GAS_PRIORITY_FEE", "50000"))       # 50K Beats fixed tip
# Seconds between bot cycles (base for adaptive delay)
CYCLE_DELAY      = int(os.getenv("CYCLE_DELAY",       "30"))
# Adaptive delay bounds and backoff factor
CYCLE_DELAY_MIN  = int(os.getenv("CYCLE_DELAY_MIN",   "15"))
CYCLE_DELAY_MAX  = int(os.getenv("CYCLE_DELAY_MAX",   "90"))
CYCLE_BACKOFF    = float(os.getenv("CYCLE_BACKOFF",    "1.5"))
# QING cache TTL in seconds (1 hour)
CACHE_TTL      = int(os.getenv("CACHE_TTL",       "3600"))
# Minimum PLS profit to bother executing (in wei)
MIN_PROFIT_WEI = int(Decimal(os.getenv("MIN_PROFIT_PLS", "5")) * Decimal(10**18))


# ── Cycle Timeout ────────────────────────────────────────────────────────────
CYCLE_TIMEOUT = int(os.getenv("CYCLE_TIMEOUT", "90"))  # seconds

# ── Supply Oracle ────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SUPPLY_INFLATION_THRESHOLD = float(os.getenv("SUPPLY_INFLATION_THRESHOLD", "0.01"))
SUPPLY_COOLDOWN_SECONDS    = int(os.getenv("SUPPLY_COOLDOWN_SECONDS", "300"))

# ── Mempool Gas ──────────────────────────────────────────────────────────────
MEMPOOL_CACHE_SECONDS = int(os.getenv("MEMPOOL_CACHE_SECONDS", "10"))

# ── Cross-Treasury Routing ───────────────────────────────────────────────────
CROSS_TREASURY_MIN_IMPROVEMENT = float(os.getenv("CROSS_TREASURY_MIN_IMPROVE", "0.10"))

# ── Spine Discovery ──────────────────────────────────────────────────────────
SPINE_ALLOW_SELF_BURN  = os.getenv("SPINE_ALLOW_SELF_BURN", "false").lower() == "true"
SPINE_DISCOVERY_TTL    = int(os.getenv("SPINE_DISCOVERY_TTL", "1800"))


class AdaptiveDelay:
    """Exponential backoff when idle, tighten when profitable."""

    def __init__(
        self,
        base: int = CYCLE_DELAY,
        lo: int = CYCLE_DELAY_MIN,
        hi: int = CYCLE_DELAY_MAX,
        backoff: float = CYCLE_BACKOFF,
    ):
        self.base = base
        self.lo = lo
        self.hi = hi
        self.backoff = backoff
        self.current = float(base)

    def after_profit(self) -> None:
        """Profitable cycle — tighten to base/2 (floor at lo)."""
        self.current = max(self.lo, self.base / 2)

    def after_skip(self) -> None:
        """All engines skipped — back off exponentially."""
        self.current = min(self.hi, self.current * self.backoff)

    def after_failure(self) -> None:
        """Engine failure or strategic success — reset to base."""
        self.current = float(self.base)

    def after_gas_high(self) -> None:
        """Gas too high — double current adaptive delay, capped."""
        self.current = min(self.hi, self.current * 2)

    def wait(self) -> None:
        import time
        time.sleep(self.current)

    @property
    def seconds(self) -> float:
        return self.current


# ─── Probe Controller (E2 adaptive sell sizing) ──────────────────────
# See docs/superpowers/specs/2026-04-08-adaptive-probe-controller-design.md
PROBE_BASELINE_PCT = 0.3              # starting impact %, matches current ~8 GIBS floor sell
PROBE_STEP_PCT = 1.0                  # linear escalation per failed probe
PROBE_MAX_IMPACT_PCT = 10.0           # safety cap before CAPPED state
PROBE_RESPONSE_WINDOW_BLOCKS = 5      # blocks to wait for arb response after a sell
PROBE_FAILURE_THRESHOLD = 2           # consecutive LOCKED failures → RE_PROBING
PROBE_CAPPED_AUTO_RESET_BLOCKS = 3    # CAPPED → PROBING after this many blocks
PROBE_CAP_LOOP_WARN_THRESHOLD = 5     # log WARN after this many cap_loop entries
PROBE_CAP_LOOP_PAUSE_THRESHOLD = 10   # PAUSED after this many cap_loop entries
PROBE_CAP_LOOP_PAUSE_BLOCKS = 30      # PAUSED → PROBING after this many blocks (~5 min)
PROBE_LP_ADD_RETRY_LIMIT = 3          # max consecutive LP-add failures before clearing target
