"""Offline delegation-grant verification for fd-cn-report.

Lets the line accept the gateway's short-lived grant tokens DIRECTLY (no gateway
in the path), proving standalone parity: a grant verified offline against the
gateway JWKS, exactly as the gateway itself does. Enable with:

    GRANT_VERIFY_ENABLED=true
    GRANT_JWKS_URL=https://mcp.finddatatech.cloud/.well-known/grant-jwks.json
    GRANT_AUD=fd-cn-report

When enabled, ``BearerAuthMiddleware`` accepts EITHER the existing shared bearer
``MCP_BEARER_TOKEN`` (fallback track) OR a valid grant (grant track). Disabled by
default, so a line without these env vars is byte-identical to before.

This module is deliberately standalone (only pyjwt + httpx, both already deps) so
a line does not import the gateway's code. Contrast the gateway side
(registry.auth.grant*), which is the issuer and the reference implementation.

Change: establish-agent-principal-plane (task 5.2).
"""

from __future__ import annotations

import json
import os
import time

import httpx
import jwt

GRANT_ISSUER = "mcp-gateway"
GRANT_ALG = "EdDSA"

_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL = 300.0


def enabled() -> bool:
    return (os.environ.get("GRANT_VERIFY_ENABLED", "").strip().lower()
            in ("1", "true", "yes", "on"))


def _jwks_url() -> str:
    return (os.environ.get("GRANT_JWKS_URL") or "").strip()


def _aud() -> str:
    return (os.environ.get("GRANT_AUD") or "").strip()


def looks_like_grant(token: str) -> bool:
    if not enabled():
        return False
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except Exception:  # noqa: BLE001
        return False
    return claims.get("iss") == GRANT_ISSUER


def _fetch_jwks(url: str, aud: str) -> dict:
    now = time.monotonic()
    if _jwks_cache["keys"] is not None and (now - _jwks_cache["fetched_at"]) < _JWKS_TTL:
        return _jwks_cache["keys"]
    resp = httpx.get(url, params={"aud": aud}, timeout=5.0)
    resp.raise_for_status()
    data = resp.json()
    _jwks_cache["keys"] = data
    _jwks_cache["fetched_at"] = now
    return data


def _public_key_from_jwk(jwk: dict):
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    x = jwk["x"]
    pad = "=" * (-len(x) % 4)
    raw = base64.urlsafe_b64decode(x + pad)
    return Ed25519PublicKey.from_public_bytes(raw)


def verify_grant(token: str) -> bool:
    """Return True iff the token is a valid grant for this line's aud."""
    url, aud = _jwks_url(), _aud()
    if not url or not aud:
        return False
    try:
        jwks = _fetch_jwks(url, aud)
        kid = jwt.get_unverified_header(token).get("kid")
        matching = [k for k in jwks.get("keys", []) if k.get("kid") == kid]
        if not matching:
            return False
        pub = _public_key_from_jwk(matching[0])
        jwt.decode(token, pub, algorithms=[GRANT_ALG], audience=aud,
                   options={"require": ["exp", "iat", "aud", "sub", "iss"]})
        return True
    except Exception:  # noqa: BLE001 - any failure => not a valid grant
        return False
