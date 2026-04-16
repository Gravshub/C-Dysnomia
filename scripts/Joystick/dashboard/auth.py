"""Shared auth for privileged dashboard endpoints.

The dashboard is advertised as read-only, but two endpoints are privileged:
 - POST /api/lp-fees/reset-baseline (mutates baseline)
 - /ws/terminal (can execute scripts and trigger bot commands)

Both require DASHBOARD_TERMINAL_TOKEN to be set in the environment. When unset,
the endpoints refuse all requests (503 / WS close 1008). This keeps the default
deploy posture safe even when the dashboard is exposed to the public internet.
"""

import hmac
import logging
from typing import Optional

from fastapi import HTTPException, Request

from . import config

logger = logging.getLogger("joystick.dashboard.auth")


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def require_admin(request: Request) -> None:
    """Raise HTTPException unless the request carries a matching bearer token.

    Returns None on success; raises on failure so FastAPI returns the error.
    """
    expected = config.DASHBOARD_TERMINAL_TOKEN
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Privileged endpoint disabled (DASHBOARD_TERMINAL_TOKEN unset)",
        )

    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = auth.split(" ", 1)[1].strip()
    if not _constant_time_eq(token, expected):
        raise HTTPException(status_code=403, detail="Invalid token")


def check_ws_token(token: Optional[str]) -> bool:
    """Validate a WebSocket auth token passed as a query param.

    Returns True when the server token is configured AND the supplied token
    matches. Returns False otherwise (including when the server has no token
    configured — the endpoint is treated as disabled).
    """
    expected = config.DASHBOARD_TERMINAL_TOKEN
    if not expected or not token:
        return False
    return _constant_time_eq(token, expected)
