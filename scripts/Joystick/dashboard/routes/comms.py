"""
JOYSTICK Mission Control — COMMS Route
VOID chat reader via Fomalhaute LogEvent logs.

GET /api/comms?blocks=50000&tail=100
Returns recent VOID chat messages decoded from on-chain logs.
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from web3 import Web3
from eth_utils import keccak

from .. import config

logger = logging.getLogger("joystick.comms")

router = APIRouter()

# ─── Constants ────────────────────────────────────────────────────
FOMALHAUTE = Web3.to_checksum_address(config.FOMALHAUTE)
LOG_TOPIC = "0x" + keccak(text="LogEvent(uint64,uint64,string)").hex()

# ─── Cache ────────────────────────────────────────────────────────
_cache = {"data": None, "ts": 0, "key": None}


# ─── Response models ──────────────────────────────────────────────

class ChatMessage(BaseModel):
    block: int
    soul: int
    aura: int
    msg: str
    tx_hash: str


class CommsResponse(BaseModel):
    block: int
    scan_range: list[int]
    messages: list[ChatMessage]
    total_found: int
    returned: int


# ─── LogEvent decoder (from void_chat_reader.py) ─────────────────

def decode_log_event(log):
    """Decode LogEvent(uint64 Soul, uint64 Aura, string LogLine)."""
    data = bytes(log["data"])
    if len(data) < 128:
        return None, None, None
    try:
        soul = int(data[0:32].hex(), 16)
        aura = int(data[32:64].hex(), 16)
        # str_offset = int(data[64:96].hex(), 16)  # always 0x60
        str_len = int(data[96:128].hex(), 16)
        msg_bytes = data[128:128 + str_len]
        msg = msg_bytes.decode("utf-8", errors="replace")
        return soul, aura, msg
    except Exception:
        return None, None, None


# ─── Log scanner ──────────────────────────────────────────────────

def scan_logs(w3: Web3, from_block: int, to_block: int) -> list[dict]:
    """Scan Fomalhaute for LogEvent in chunks."""
    all_logs = []
    chunk = config.COMMS_CHUNK_SIZE

    for start in range(from_block, to_block + 1, chunk):
        end = min(start + chunk - 1, to_block)
        try:
            logs = w3.eth.get_logs({
                "fromBlock": hex(start),
                "toBlock": hex(end),
                "address": FOMALHAUTE,
                "topics": [LOG_TOPIC],
            })
            all_logs.extend(logs)
        except Exception as e:
            logger.warning(f"Log scan chunk {start}-{end} failed: {e}")

    return all_logs


# ─── Endpoint ─────────────────────────────────────────────────────

@router.get("/comms", response_model=CommsResponse)
async def get_comms(
    blocks: int = Query(default=50000, ge=1000, le=500000, description="Block lookback range"),
    tail: int = Query(default=100, ge=1, le=500, description="Return last N messages"),
):
    """Read recent VOID chat from Fomalhaute LogEvent logs."""
    global _cache

    cache_key = f"{blocks}:{tail}"
    now = time.time()

    # Return cached if fresh
    if (_cache["data"] is not None
            and _cache["key"] == cache_key
            and now - _cache["ts"] < config.COMMS_CACHE_TTL):
        return _cache["data"]

    # Connect to RPC
    w3 = Web3(Web3.HTTPProvider(config.RPC_READ))
    try:
        current_block = w3.eth.block_number
    except Exception as e:
        logger.error(f"RPC failed: {e}")
        return CommsResponse(
            block=0, scan_range=[0, 0], messages=[], total_found=0, returned=0
        )

    from_block = max(current_block - blocks, 0)

    # Scan
    raw_logs = scan_logs(w3, from_block, current_block)
    raw_logs.sort(key=lambda l: (l["blockNumber"], l["logIndex"]))

    # Decode all
    decoded = []
    for log in raw_logs:
        soul, aura, msg = decode_log_event(log)
        if msg is None:
            continue
        decoded.append(ChatMessage(
            block=log["blockNumber"],
            soul=soul,
            aura=aura,
            msg=msg,
            tx_hash=log["transactionHash"].hex() if isinstance(log["transactionHash"], bytes) else str(log["transactionHash"]),
        ))

    total = len(decoded)
    recent = decoded[-tail:]

    result = CommsResponse(
        block=current_block,
        scan_range=[from_block, current_block],
        messages=recent,
        total_found=total,
        returned=len(recent),
    )

    # Cache
    _cache = {"data": result, "ts": now, "key": cache_key}

    logger.info(f"COMMS: scanned {blocks} blocks, found {total} msgs, returned {len(recent)}")
    return result
