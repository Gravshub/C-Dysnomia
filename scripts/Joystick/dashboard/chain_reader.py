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
