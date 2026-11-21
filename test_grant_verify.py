"""Offline grant verification for fd-cn-report (establish-agent-principal-plane 5.2).

Signs with the gateway's Ed25519/HKDF scheme, serves the JWKS via a monkeypatched
httpx.get, and asserts the line verifies it offline — no gateway in the path.
Also asserts rejection: wrong aud, foreign key, disabled.
"""

import json
import os

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import grant_verify

SEED = b"L" * 32


def _signing_key(aud: str, gen: int = 1) -> ed25519.Ed25519PrivateKey:
    info = b"grant-signing-v1:" + f"{aud}:{gen}".encode()
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(SEED)
    return ed25519.Ed25519PrivateKey.from_private_bytes(derived)


def _jwk(aud: str, gen: int = 1) -> dict:
    import base64

    pub = _signing_key(aud, gen).public_key()
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"kty": "OKP", "crv": "Ed25519", "x": x, "kid": f"{aud}:{gen}"}


def _sign(aud: str, *, iss="mcp-gateway") -> str:
    k = _signing_key(aud)
    pem = k.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    import time

    now = int(time.time())
    return jwt.encode(
        {"iss": iss, "sub": "u1", "aud": aud, "scope": ["line:read"], "tenant": "t1",
         "run": "r1", "iat": now, "exp": now + 300},
        pem, algorithm="EdDSA", headers={"kid": f"{aud}:1"},
    )


@pytest.fixture
def grant_env(monkeypatch):
    monkeypatch.setenv("GRANT_VERIFY_ENABLED", "true")
    monkeypatch.setenv("GRANT_JWKS_URL", "https://gw/api/jwks")
    monkeypatch.setenv("GRANT_AUD", "fd-cn-report")
    grant_verify._jwks_cache = {"keys": None, "fetched_at": 0.0}

    def fake_get(url, params=None, timeout=None):
        aud = (params or {}).get("aud")
        req = httpx.Request("GET", url)
        return httpx.Response(200, json={"keys": [_jwk(aud)]}, request=req)

    monkeypatch.setattr(grant_verify.httpx, "get", fake_get)


def test_verify_valid_grant(grant_env):
    token = _sign("fd-cn-report")
    assert grant_verify.looks_like_grant(token) is True
    assert grant_verify.verify_grant(token) is True


def test_wrong_aud_rejected(grant_env):
    token = _sign("other-service")
    # looks_like_grant is iss-based; verify must reject on aud mismatch.
    assert grant_verify.verify_grant(token) is False


def test_foreign_key_rejected(grant_env, monkeypatch):
    # Serve a JWKS for the right aud but a DIFFERENT key than the signer used.
    def fake_bad(url, params=None, timeout=None):
        req = httpx.Request("GET", url)
        return httpx.Response(200, json={"keys": [_jwk("fd-cn-report", gen=2)]}, request=req)

    monkeypatch.setattr(grant_verify.httpx, "get", fake_bad)
    token = _sign("fd-cn-report")
    assert grant_verify.verify_grant(token) is False


def test_disabled_rejects(monkeypatch):
    monkeypatch.delenv("GRANT_VERIFY_ENABLED", raising=False)
    token = _sign("fd-cn-report")
    assert grant_verify.enabled() is False
    assert grant_verify.looks_like_grant(token) is False
