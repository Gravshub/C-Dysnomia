"""
JOYSTICK Mission Control — Chain Reader
Multicall3-batched on-chain reads for the dashboard.

Follows the PulseChain RPC skill patterns:
- g4mm4 for reads (faster individual calls)
- Multicall3 at 0xcA11bde... for batched reads
- Gas denominated in Beats (÷ 10^9 from Impulses)
- Return data limit: 512KB per eth_call
"""

import logging
from typing import Optional
from web3 import Web3
from eth_abi import decode as abi_decode, encode as abi_encode

from . import config

logger = logging.getLogger("joystick.chain_reader")

# ─── Function selectors (pre-computed, no contract object overhead) ──
SEL_BALANCE_OF   = Web3.keccak(text="balanceOf(address)")[:4]
SEL_DECIMALS     = Web3.keccak(text="decimals()")[:4]
SEL_SYMBOL       = Web3.keccak(text="symbol()")[:4]
SEL_GET_RESERVES = Web3.keccak(text="getReserves()")[:4]
SEL_TOKEN0       = Web3.keccak(text="token0()")[:4]
SEL_TOKEN1       = Web3.keccak(text="token1()")[:4]
SEL_GET_PAIR     = Web3.keccak(text="getPair(address,address)")[:4]

# ─── TGSv8 selectors ───────────────────────────────────────────────
SEL_OWNER        = Web3.keccak(text="owner()")[:4]
SEL_PAUSED       = Web3.keccak(text="paused()")[:4]
SEL_AUTHORIZED   = Web3.keccak(text="authorized(address)")[:4]
SEL_OP_NONCE     = Web3.keccak(text="opNonce()")[:4]
SEL_REGISTRY_LEN = Web3.keccak(text="registryLen()")[:4]
SEL_MAX_BATCH    = Web3.keccak(text="maxBatch()")[:4]
SEL_NATIVE_BAL   = Web3.keccak(text="nativeBal()")[:4]
SEL_MINTER_V4    = Web3.keccak(text="minterV4()")[:4]
SEL_MINTER_V3    = Web3.keccak(text="minterV3()")[:4]
SEL_MV           = Web3.keccak(text="mv()")[:4]
SEL_ROUTER_V1    = Web3.keccak(text="routerV1()")[:4]
SEL_ROUTER_V2    = Web3.keccak(text="routerV2()")[:4]
SEL_BATCH_BAL    = Web3.keccak(text="batchBal(address[])")[:4]

# ─── TGSv8+ selectors ──────────────────────────────────────────────
SEL_LAU              = Web3.keccak(text="lau()")[:4]
SEL_PAY_TOKEN        = Web3.keccak(text="payToken()")[:4]
SEL_WPLS             = Web3.keccak(text="wpls()")[:4]
SEL_FACTORY_V1       = Web3.keccak(text="factoryV1()")[:4]
SEL_FACTORY_V2       = Web3.keccak(text="factoryV2()")[:4]
SEL_TOTAL_LAU_MINTED = Web3.keccak(text="totalLauMinted()")[:4]
SEL_TOTAL_PAY_SPENT  = Web3.keccak(text="totalPayTokenSpent()")[:4]
SEL_TOTAL_LP_BURNED  = Web3.keccak(text="totalLpBurned()")[:4]
SEL_OP_COUNTER       = Web3.keccak(text="opCounter()")[:4]
SEL_MINTABLE_LAU     = Web3.keccak(text="mintableLAU()")[:4]
SEL_LAU_REMAINING    = Web3.keccak(text="lauRemaining()")[:4]

# Multicall3 ABI (aggregate3 only — all we need for reads)
MC3_ABI = [{
    "inputs": [{"components": [
        {"name": "target", "type": "address"},
        {"name": "allowFailure", "type": "bool"},
        {"name": "callData", "type": "bytes"}
    ], "name": "calls", "type": "tuple[]"}],
    "name": "aggregate3",
    "outputs": [{"components": [
        {"name": "success", "type": "bool"},
        {"name": "returnData", "type": "bytes"}
    ], "name": "returnData", "type": "tuple[]"}],
    "stateMutability": "view", "type": "function"
}]


class ChainReader:
    """Read-only on-chain data fetcher for the JOYSTICK dashboard.
    
    Uses Multicall3 to batch all reads into minimal RPC round-trips.
    Designed to be stateless — each method call is a fresh read.
    """

    def __init__(self, rpc_url: Optional[str] = None):
        self.rpc_url = rpc_url or config.RPC_READ
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 60}))
        self.mc3 = self.w3.eth.contract(
            address=Web3.to_checksum_address(config.MULTICALL3),
            abi=MC3_ABI,
        )
        logger.info(f"ChainReader initialized: {self.rpc_url}")

    def _encode_balance_of(self, token: str, holder: str) -> bytes:
        """Encode balanceOf(address) calldata."""
        return SEL_BALANCE_OF + abi_encode(["address"], [Web3.to_checksum_address(holder)])

    def _multicall(self, calls: list[tuple[str, bytes]]) -> list[tuple[bool, bytes]]:
        """Execute a batch of calls via Multicall3.aggregate3.
        
        Args:
            calls: list of (target_address, calldata) tuples
            
        Returns:
            list of (success, returnData) tuples
        """
        if not calls:
            return []

        mc_calls = [
            (Web3.to_checksum_address(target), True, data)
            for target, data in calls
        ]

        try:
            results = self.mc3.functions.aggregate3(mc_calls).call()
            return [(r[0], r[1]) for r in results]
        except Exception as e:
            logger.error(f"Multicall3 failed: {e}")
            return [(False, b"") for _ in calls]

    # ─── Public methods ──────────────────────────────────────────────

    def get_block_number(self) -> int:
        """Current block number."""
        try:
            return self.w3.eth.block_number
        except Exception as e:
            logger.error(f"get_block_number failed: {e}")
            return 0

    def get_gas_price_impulses(self) -> int:
        """Raw gas price in Impulses (wei-equivalent).
        Divide by 10^9 for Beats (PulseChain's gas unit).
        """
        try:
            return self.w3.eth.gas_price
        except Exception as e:
            logger.error(f"get_gas_price failed: {e}")
            return 0

    def get_gas_price_beats(self) -> float:
        """Gas price in Beats (human-readable PulseChain unit)."""
        return self.get_gas_price_impulses() / 1e9

    def get_pls_balance(self, address: str) -> int:
        """Native PLS balance in wei (Impulses)."""
        try:
            return self.w3.eth.get_balance(Web3.to_checksum_address(address))
        except Exception as e:
            logger.error(f"get_pls_balance failed for {address}: {e}")
            return 0

    def get_all_balances(self, holder: str) -> dict[str, int]:
        """Fetch PLS + all token balances for a holder in one Multicall3 batch.
        
        Returns dict of symbol → balance_wei (int).
        PLS balance fetched separately (native, not ERC20).
        """
        holder_cs = Web3.to_checksum_address(holder)

        # Native PLS balance (separate call — not ERC20)
        pls_wei = self.get_pls_balance(holder)

        # Build ERC20 balanceOf calls
        tokens = {
            sym: addr for sym, addr in config.TOKEN_REGISTRY.items()
            if addr is not None  # skip PLS (native)
        }

        calls = [
            (addr, self._encode_balance_of(addr, holder_cs))
            for addr in tokens.values()
        ]

        results = self._multicall(calls)

        balances = {"PLS": pls_wei}
        for (sym, addr), (success, data) in zip(tokens.items(), results):
            if success and len(data) >= 32:
                try:
                    (bal,) = abi_decode(["uint256"], data)
                    balances[sym] = bal
                except Exception:
                    balances[sym] = 0
            else:
                balances[sym] = 0

        return balances

    def get_pair_reserves(self, pair_address: str) -> Optional[tuple[int, int, int]]:
        """Get reserves for a Uniswap V2 pair.
        
        Returns (reserve0, reserve1, blockTimestampLast) or None on failure.
        """
        calls = [
            (pair_address, SEL_GET_RESERVES),
            (pair_address, SEL_TOKEN0),
        ]
        results = self._multicall(calls)

        if not results[0][0] or len(results[0][1]) < 96:
            return None

        try:
            r0, r1, ts = abi_decode(["uint112", "uint112", "uint32"], results[0][1])
            return (r0, r1, ts)
        except Exception:
            return None

    def get_gibs_pls_price(self, gibs_wpls_pair: str) -> Optional[float]:
        """Get GIBS price in PLS from the GIBS/WPLS pair.
        
        Returns PLS per GIBS, or None if pair isn't readable.
        Uses getAmountsOut logic: price = reserve_wpls / reserve_gibs
        (adjusted for which token is token0).
        """
        calls = [
            (gibs_wpls_pair, SEL_GET_RESERVES),
            (gibs_wpls_pair, SEL_TOKEN0),
        ]
        results = self._multicall(calls)

        if not all(r[0] for r in results):
            return None

        try:
            r0, r1, _ = abi_decode(["uint112", "uint112", "uint32"], results[0][1])
            (token0,) = abi_decode(["address"], results[1][1])

            # Determine which reserve is GIBS and which is WPLS
            gibs_addr = Web3.to_checksum_address(config.GIBS_LAU)
            if token0.lower() == gibs_addr.lower():
                # token0 = GIBS, token1 = WPLS
                return r1 / r0 if r0 > 0 else None
            else:
                # token0 = WPLS, token1 = GIBS
                return r0 / r1 if r1 > 0 else None
        except Exception as e:
            logger.error(f"get_gibs_pls_price failed: {e}")
            return None

    def get_tgsv8_state(self) -> dict:
        """Fetch full TGSv8 contract state via Multicall3.

        Returns dict with owner, paused, auth checks, refs, registry info,
        native PLS balance, and token balances.
        """
        tgsv8 = Web3.to_checksum_address(config.TGSV8)
        joey = Web3.to_checksum_address(config.JOEY_WALLET)
        minter = Web3.to_checksum_address(config.MINTER_WALLET) if config.MINTER_WALLET else None
        seller = Web3.to_checksum_address(config.SELLER_WALLET) if config.SELLER_WALLET else None

        # Build multicall batch
        calls = [
            (tgsv8, SEL_OWNER),                                                    # 0: owner
            (tgsv8, SEL_PAUSED),                                                   # 1: paused
            (tgsv8, SEL_AUTHORIZED + abi_encode(["address"], [joey])),              # 2: auth joey
            (tgsv8, SEL_OP_NONCE),                                                 # 3: opNonce
            (tgsv8, SEL_REGISTRY_LEN),                                             # 4: registryLen
            (tgsv8, SEL_MAX_BATCH),                                                # 5: maxBatch
            (tgsv8, SEL_NATIVE_BAL),                                               # 6: nativeBal
            (tgsv8, SEL_MINTER_V4),                                                # 7: minterV4
            (tgsv8, SEL_MINTER_V3),                                                # 8: minterV3
            (tgsv8, SEL_MV),                                                       # 9: mv
            (tgsv8, SEL_ROUTER_V1),                                                # 10: routerV1
            (tgsv8, SEL_ROUTER_V2),                                                # 11: routerV2
        ]

        # Auth checks for minter/seller (if configured)
        auth_minter_idx = None
        auth_seller_idx = None
        if minter:
            auth_minter_idx = len(calls)
            calls.append((tgsv8, SEL_AUTHORIZED + abi_encode(["address"], [minter])))
        if seller:
            auth_seller_idx = len(calls)
            calls.append((tgsv8, SEL_AUTHORIZED + abi_encode(["address"], [seller])))

        # batchBal for tracked tokens
        tracked_tokens = [
            Web3.to_checksum_address(addr) for sym, addr in config.TOKEN_REGISTRY.items()
            if addr is not None
        ]
        tracked_syms = [sym for sym, addr in config.TOKEN_REGISTRY.items() if addr is not None]
        batch_bal_idx = len(calls)
        calls.append((tgsv8, SEL_BATCH_BAL + abi_encode(["address[]"], [tracked_tokens])))

        results = self._multicall(calls)

        def _addr(idx):
            ok, data = results[idx]
            if ok and len(data) >= 32:
                (a,) = abi_decode(["address"], data)
                return a
            return None

        def _uint(idx):
            ok, data = results[idx]
            if ok and len(data) >= 32:
                (v,) = abi_decode(["uint256"], data)
                return v
            return 0

        def _bool(idx):
            ok, data = results[idx]
            if ok and len(data) >= 32:
                (v,) = abi_decode(["bool"], data)
                return v
            return False

        owner = _addr(0)
        refs = {
            "minter_v4": _addr(7),
            "minter_v3": _addr(8),
            "mv":        _addr(9),
            "router_v1": _addr(10),
            "router_v2": _addr(11),
        }

        # Check refs against expected values
        refs_valid = all(
            refs.get(k, "").lower() == v.lower()
            for k, v in config.TGSV8_EXPECTED_REFS.items()
            if refs.get(k)
        )

        # Parse batchBal
        token_balances = {}
        ok, data = results[batch_bal_idx]
        if ok and len(data) >= 64:
            try:
                (bals,) = abi_decode(["uint256[]"], data)
                for sym, bal in zip(tracked_syms, bals):
                    token_balances[sym] = bal / 1e18
            except Exception:
                pass

        native_pls = _uint(6) / 1e18

        return {
            "address": config.TGSV8,
            "owner": owner,
            "owner_is_joey": owner.lower() == joey.lower() if owner else False,
            "paused": _bool(1),
            "authorized": {
                "joey": _bool(2),
                "minter": _bool(auth_minter_idx) if auth_minter_idx is not None else None,
                "seller": _bool(auth_seller_idx) if auth_seller_idx is not None else None,
            },
            "op_nonce": _uint(3),
            "registry_len": _uint(4),
            "max_batch": _uint(5),
            "native_pls": round(native_pls, 4),
            "token_balances": token_balances,
            "refs": refs,
            "refs_valid": refs_valid,
        }

    def get_tgsv8plus_state(self) -> dict:
        """Fetch full TGSv8+ contract state via Multicall3.

        Returns dict with owner, auth checks, refs, stats, token balances.
        """
        plus = Web3.to_checksum_address(config.TGSV8PLUS)
        joey = Web3.to_checksum_address(config.JOEY_WALLET)
        minter = Web3.to_checksum_address(config.MINTER_WALLET) if config.MINTER_WALLET else None

        calls = [
            (plus, SEL_OWNER),                                                     # 0: owner
            (plus, SEL_AUTHORIZED + abi_encode(["address"], [joey])),               # 1: auth joey
            (plus, SEL_LAU),                                                        # 2: lau
            (plus, SEL_PAY_TOKEN),                                                  # 3: payToken
            (plus, SEL_WPLS),                                                       # 4: wpls
            (plus, SEL_ROUTER_V1),                                                  # 5: routerV1
            (plus, SEL_ROUTER_V2),                                                  # 6: routerV2
            (plus, SEL_FACTORY_V1),                                                 # 7: factoryV1
            (plus, SEL_FACTORY_V2),                                                 # 8: factoryV2
            (plus, SEL_TOTAL_LAU_MINTED),                                           # 9: totalLauMinted
            (plus, SEL_TOTAL_PAY_SPENT),                                            # 10: totalPayTokenSpent
            (plus, SEL_TOTAL_LP_BURNED),                                            # 11: totalLpBurned
            (plus, SEL_OP_COUNTER),                                                 # 12: opCounter
            (plus, SEL_MINTABLE_LAU),                                               # 13: mintableLAU
            (plus, SEL_LAU_REMAINING),                                              # 14: lauRemaining
        ]

        auth_minter_idx = None
        if minter:
            auth_minter_idx = len(calls)
            calls.append((plus, SEL_AUTHORIZED + abi_encode(["address"], [minter])))

        # batchBal for tracked tokens
        tracked_tokens = [
            Web3.to_checksum_address(addr) for sym, addr in config.TOKEN_REGISTRY.items()
            if addr is not None
        ]
        tracked_syms = [sym for sym, addr in config.TOKEN_REGISTRY.items() if addr is not None]
        batch_bal_idx = len(calls)
        calls.append((plus, SEL_BATCH_BAL + abi_encode(["address[]"], [tracked_tokens])))

        # Native PLS balance via eth_getBalance
        plus_pls = self.get_pls_balance(plus)

        results = self._multicall(calls)

        def _addr(idx):
            ok, data = results[idx]
            if ok and len(data) >= 32:
                (a,) = abi_decode(["address"], data)
                return a
            return None

        def _uint(idx):
            ok, data = results[idx]
            if ok and len(data) >= 32:
                (v,) = abi_decode(["uint256"], data)
                return v
            return 0

        def _bool(idx):
            ok, data = results[idx]
            if ok and len(data) >= 32:
                (v,) = abi_decode(["bool"], data)
                return v
            return False

        owner = _addr(0)
        refs = {
            "lau":        _addr(2),
            "pay_token":  _addr(3),
            "wpls":       _addr(4),
            "router_v1":  _addr(5),
            "router_v2":  _addr(6),
            "factory_v1": _addr(7),
            "factory_v2": _addr(8),
        }

        refs_valid = all(
            refs.get(k, "").lower() == v.lower()
            for k, v in config.TGSV8PLUS_EXPECTED_REFS.items()
            if refs.get(k)
        )

        # Parse batchBal
        token_balances = {}
        ok, data = results[batch_bal_idx]
        if ok and len(data) >= 64:
            try:
                (bals,) = abi_decode(["uint256[]"], data)
                for sym, bal in zip(tracked_syms, bals):
                    token_balances[sym] = bal / 1e18
            except Exception:
                pass

        return {
            "address": config.TGSV8PLUS,
            "owner": owner,
            "owner_is_joey": owner.lower() == joey.lower() if owner else False,
            "authorized": {
                "joey": _bool(1),
                "minter": _bool(auth_minter_idx) if auth_minter_idx is not None else None,
            },
            "stats": {
                "total_lau_minted": _uint(9) / 1e18,
                "total_pay_token_spent": _uint(10) / 1e18,
                "total_lp_burned": _uint(11) / 1e18,
                "op_counter": _uint(12),
                "mintable_lau": _uint(13),
                "lau_remaining": _uint(14),
            },
            "native_pls": round(plus_pls / 1e18, 4),
            "token_balances": token_balances,
            "refs": refs,
            "refs_valid": refs_valid,
        }

    # ─── Pair address cache (pairs never change) ────────────────────
    _pair_cache: dict[str, str] = {}

    def _discover_pairs(self, tokens: dict[str, str]) -> dict[str, str]:
        """Discover best PulseX pair (V1 or V2) for each token vs WPLS.

        Returns dict of symbol → pair_address. Cached after first call.
        """
        wpls = Web3.to_checksum_address(config.WPLS)
        v1_factory = Web3.to_checksum_address(config.PULSEX_V1_FACTORY)
        v2_factory = Web3.to_checksum_address(config.PULSEX_V2_FACTORY)

        # Check cache first
        uncached = {s: a for s, a in tokens.items() if s not in self._pair_cache}
        if not uncached:
            return {s: self._pair_cache[s] for s in tokens if s in self._pair_cache}

        # getPair(tokenA, tokenB) on both factories
        calls = []
        call_map = []  # (symbol, factory_label)
        for sym, addr in uncached.items():
            tok = Web3.to_checksum_address(addr)
            cd = SEL_GET_PAIR + abi_encode(["address", "address"], [tok, wpls])
            calls.append((v1_factory, cd))
            call_map.append((sym, "V1"))
            calls.append((v2_factory, cd))
            call_map.append((sym, "V2"))

        results = self._multicall(calls)

        # Collect pairs per symbol
        pairs_found: dict[str, dict[str, str]] = {}  # sym → {V1: addr, V2: addr}
        zero = "0x" + "0" * 40
        for (sym, factory), (ok, data) in zip(call_map, results):
            if ok and len(data) >= 32:
                try:
                    (addr,) = abi_decode(["address"], data)
                    if addr and addr != zero:
                        pairs_found.setdefault(sym, {})[factory] = addr
                except Exception:
                    pass

        # For each token, pick best pair (prefer V2, fall back to V1)
        for sym in uncached:
            pf = pairs_found.get(sym, {})
            pair = pf.get("V2") or pf.get("V1")
            if pair:
                self._pair_cache[sym] = pair

        return {s: self._pair_cache[s] for s in tokens if s in self._pair_cache}

    def get_token_prices_pls(self) -> dict[str, float]:
        """Get PLS price per token for all TOKEN_REGISTRY entries.

        Uses reserve ratios from the best WPLS pair for each token.
        Returns dict of symbol → PLS-per-token. PLS=1.0, WPLS=1.0.
        """
        wpls_lower = config.WPLS.lower()

        # Tokens that need pricing (not PLS, not WPLS)
        priceable = {
            sym: addr for sym, addr in config.TOKEN_REGISTRY.items()
            if addr is not None and addr.lower() != wpls_lower
        }

        pairs = self._discover_pairs(priceable)
        if not pairs:
            return {"PLS": 1.0, "WPLS": 1.0}

        # Batch getReserves + token0 for all pairs
        calls = []
        pair_syms = []
        for sym in pairs:
            pair = pairs[sym]
            calls.append((pair, SEL_GET_RESERVES))
            calls.append((pair, SEL_TOKEN0))
            pair_syms.append(sym)

        results = self._multicall(calls)

        prices: dict[str, float] = {"PLS": 1.0, "WPLS": 1.0}
        for i, sym in enumerate(pair_syms):
            res_ok, res_data = results[i * 2]
            t0_ok, t0_data = results[i * 2 + 1]
            if not (res_ok and t0_ok and len(res_data) >= 96 and len(t0_data) >= 32):
                continue
            try:
                r0, r1, _ = abi_decode(["uint112", "uint112", "uint32"], res_data)
                (token0,) = abi_decode(["address"], t0_data)
                if r0 == 0 or r1 == 0:
                    continue
                # Which side is WPLS?
                if token0.lower() == wpls_lower:
                    # token0=WPLS, token1=token → price = r0/r1
                    prices[sym] = r0 / r1
                else:
                    # token0=token, token1=WPLS → price = r1/r0
                    prices[sym] = r1 / r0
            except Exception:
                continue

        return prices

    # PLS/USD cache (CoinGecko rate-limited, cache for 60s)
    _pls_usd_cache: float = 0.0
    _pls_usd_cache_ts: float = 0.0

    def get_pls_usd_price(self) -> float:
        """Get PLS price in USD from CoinGecko API.

        pDAI/pUSDC on PulseChain are NOT pegged to $1 (forked tokens),
        so on-chain reserves give wrong USD prices. Use external oracle.
        Cached for 60 seconds to respect rate limits.
        """
        import time
        import requests

        now = time.time()
        if self._pls_usd_cache > 0 and (now - self._pls_usd_cache_ts) < 60:
            return self._pls_usd_cache

        try:
            resp = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "pulsechain", "vs_currencies": "usd"},
                timeout=5,
            )
            if resp.status_code == 200:
                price = resp.json().get("pulsechain", {}).get("usd", 0.0)
                if price > 0:
                    self._pls_usd_cache = price
                    self._pls_usd_cache_ts = now
                    return price
        except Exception as e:
            logger.warning(f"CoinGecko PLS/USD fetch failed: {e}")

        return self._pls_usd_cache  # return stale cache if fetch fails

    def get_multi_wallet_balances(self) -> dict[str, dict[str, int]]:
        """Fetch PLS + token balances for all portfolio wallets in one batch.

        Returns dict of wallet_label → {symbol: balance_wei}.
        """
        wallets = config.PORTFOLIO_WALLETS
        erc_tokens = {
            sym: addr for sym, addr in config.TOKEN_REGISTRY.items()
            if addr is not None
        }

        # Native PLS balances (separate — not ERC20)
        result: dict[str, dict[str, int]] = {}
        for label, wallet in wallets.items():
            result[label] = {"PLS": self.get_pls_balance(wallet)}

        # ERC20 balanceOf calls: wallets × tokens
        calls = []
        call_map = []  # (wallet_label, symbol)
        for label, wallet in wallets.items():
            holder = Web3.to_checksum_address(wallet)
            for sym, addr in erc_tokens.items():
                calls.append((addr, self._encode_balance_of(addr, holder)))
                call_map.append((label, sym))

        mc_results = self._multicall(calls)
        for (label, sym), (ok, data) in zip(call_map, mc_results):
            if ok and len(data) >= 32:
                try:
                    (bal,) = abi_decode(["uint256"], data)
                    result[label][sym] = bal
                except Exception:
                    result[label][sym] = 0
            else:
                result[label][sym] = 0

        return result

    def get_mint_economics(self, gas_price_impulses: int) -> dict:
        """Fetch live WM and AFF mint economics via getAmountsOut.

        Uses Multicall3 to batch all price queries in one RPC round-trip.
        Returns cost-per-token data for WM minting and each AFF BuyWith route.
        """
        # Router getAmountsOut selector
        sel_amounts_out = Web3.keccak(text="getAmountsOut(uint256,address[])")[:4]
        router_v2 = Web3.to_checksum_address(config.PULSEX_V2_ROUTER)
        wpls = Web3.to_checksum_address(config.WPLS)
        wm = Web3.to_checksum_address(config.MV_TOKEN)
        aff = Web3.to_checksum_address(config.AFFECTION)

        def _amounts_out_calldata(amount_wei: int, path: list[str]) -> bytes:
            return sel_amounts_out + abi_encode(
                ["uint256", "address[]"],
                [amount_wei, [Web3.to_checksum_address(a) for a in path]],
            )

        # Build Multicall3 batch:
        # 0: WM → WPLS (1 WM value)
        # 1: WM → WPLS (10 WM value)
        # 2: AFF → WPLS (1 AFF DEX value)
        # 3+: payment_token → WPLS for each AFF route (1 unit of payment token)
        calls = [
            (router_v2, _amounts_out_calldata(int(1e18), [wm, wpls])),       # 0
            (router_v2, _amounts_out_calldata(int(10e18), [wm, wpls])),      # 1
            (router_v2, _amounts_out_calldata(int(1e18), [aff, wpls])),      # 2
        ]
        route_indices = {}
        for i, route in enumerate(config.AFF_ROUTES):
            idx = len(calls)
            route_indices[route["name"]] = idx
            # Use token-specific decimals (e.g. pUSDC = 6, default 18)
            token_decimals = route.get("decimals", 18)
            one_token_wei = 10 ** token_decimals
            calls.append((
                router_v2,
                _amounts_out_calldata(one_token_wei, [route["addr"], wpls]),
            ))

        results = self._multicall(calls)

        def _parse_amounts_out(idx: int) -> int:
            ok, data = results[idx]
            if ok and len(data) >= 64:
                try:
                    (amounts,) = abi_decode(["uint256[]"], data)
                    return amounts[-1]  # last element = output amount
                except Exception:
                    pass
            return 0

        # WM economics
        wm_value_1 = _parse_amounts_out(0) / 1e18    # PLS for 1 WM sold
        wm_value_10 = _parse_amounts_out(1) / 1e18   # PLS for 10 WM sold
        gas_price_pls = gas_price_impulses / 1e18     # PLS per gas unit

        wm_gas_1 = config.WM_MINT_GAS_PER_TOKEN * 1
        wm_gas_10 = config.WM_MINT_GAS_PER_TOKEN * 10
        wm_mint_cost_1 = round(wm_gas_1 * gas_price_pls, 4)
        wm_mint_cost_10 = round(wm_gas_10 * gas_price_pls, 4)

        # AFF economics
        aff_dex_value = _parse_amounts_out(2) / 1e18  # PLS per 1 AFF on DEX

        # Gas cost to run 1 loop of multiBuyWith (yields 3 AFF)
        aff_gas_total = config.AFF_BUYWITH_GAS_BASE + config.AFF_SWAP_OVERHEAD
        aff_gas_pls = aff_gas_total * gas_price_pls

        aff_routes = []
        cheapest = None
        for route in config.AFF_ROUTES:
            name = route["name"]
            per_aff = route["per_aff"]
            idx = route_indices[name]
            # PLS value of 1 payment token (raw result is in wei/1e18)
            tok_pls = _parse_amounts_out(idx) / 1e18
            if tok_pls <= 0:
                continue
            # PLS cost of payment tokens per 1 AFF
            payment_cost = per_aff * tok_pls
            # Gas per AFF (1 loop = 3 AFF, amortize)
            gas_per_aff = aff_gas_pls / 3
            total_per_aff = payment_cost + gas_per_aff

            entry = {
                "name": name,
                "payment_pls": round(payment_cost, 4),
                "gas_pls": round(gas_per_aff, 4),
                "total_pls": round(total_per_aff, 4),
                "profitable": total_per_aff < aff_dex_value,
            }
            aff_routes.append(entry)
            if cheapest is None or total_per_aff < cheapest["total_pls"]:
                cheapest = entry

        # Mint multiplier: DEX sell value / cheapest mint cost
        mint_multiplier = 0.0
        if cheapest and cheapest["total_pls"] > 0:
            mint_multiplier = round(aff_dex_value / cheapest["total_pls"], 4)

        return {
            "wm": {
                "mint_cost_1": wm_mint_cost_1,
                "mint_cost_10": wm_mint_cost_10,
                "dex_value_1": round(wm_value_1, 4),
                "dex_value_10": round(wm_value_10, 4),
            },
            "aff": {
                "dex_value": round(aff_dex_value, 4),
                "cheapest_route": cheapest["name"] if cheapest else None,
                "cheapest_cost": cheapest["total_pls"] if cheapest else None,
                "mint_multiplier": mint_multiplier,
                "routes": aff_routes,
            },
        }

    def get_dashboard_snapshot(self) -> dict:
        """Fetch all data the dashboard needs in minimal RPC calls.
        
        Batches: 
        1. eth_blockNumber + eth_gasPrice (2 individual calls)
        2. eth_getBalance for Joey wallet + TGSv8 (2 calls)
        3. Multicall3 batch: all token balances (N calls in 1 RPC round-trip)
        
        Total: ~4 RPC round-trips for the entire dashboard.
        """
        block = self.get_block_number()
        gas_impulses = self.get_gas_price_impulses()
        gas_beats = gas_impulses / 1e9

        # Joey wallet balances (native + ERC20 via Multicall3)
        balances = self.get_all_balances(config.JOEY_WALLET)

        # TGSv8 contract PLS balance
        tgsv8_pls = self.get_pls_balance(config.TGSV8)

        return {
            "block_number": block,
            "gas_price_impulses": gas_impulses,
            "gas_price_beats": gas_beats,
            "balances": balances,  # symbol → wei
            "tgsv8_pls_wei": tgsv8_pls,
        }


# ─── Module-level singleton ─────────────────────────────────────────
_reader: Optional[ChainReader] = None


def get_reader() -> ChainReader:
    """Get or create the singleton ChainReader."""
    global _reader
    if _reader is None:
        _reader = ChainReader()
    return _reader
