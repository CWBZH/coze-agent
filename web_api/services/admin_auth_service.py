from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any


SESSION_COOKIE_NAME = "ie_admin_session"
DEFAULT_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


class AdminAuthError(ValueError):
    """Raised when the web admin session is missing or invalid."""


@dataclass(frozen=True)
class AdminUser:
    username: str


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class AdminAuthService:
    """Stateless signed-cookie auth for the single-operator Web Admin."""

    def __init__(self) -> None:
        self.username = os.getenv("WEB_ADMIN_USERNAME", "admin").strip() or "admin"
        self.password = os.getenv("WEB_ADMIN_PASSWORD", "")
        self.password_hash = os.getenv("WEB_ADMIN_PASSWORD_SHA256", "")
        self.session_secret = (
            os.getenv("WEB_ADMIN_SESSION_SECRET")
            or os.getenv("SHOP_AUTH_ENCRYPTION_KEY")
            or "dev-insecure-web-admin-session-secret"
        )
        self.cookie_secure = _truthy(os.getenv("WEB_ADMIN_COOKIE_SECURE"))
        self.ttl_seconds = int(os.getenv("WEB_ADMIN_SESSION_TTL_SECONDS", str(DEFAULT_SESSION_TTL_SECONDS)))

    @property
    def configured(self) -> bool:
        return bool(self.password or self.password_hash)

    @property
    def insecure_default_secret(self) -> bool:
        return self.session_secret == "dev-insecure-web-admin-session-secret"

    def verify_credentials(self, username: str, password: str) -> bool:
        if not self.configured:
            return False
        if not hmac.compare_digest(str(username or ""), self.username):
            return False
        if self.password_hash:
            digest = hashlib.sha256(str(password or "").encode("utf-8")).hexdigest()
            return hmac.compare_digest(digest, self.password_hash)
        return hmac.compare_digest(str(password or ""), self.password)

    def issue_token(self, username: str, remember: bool = True) -> tuple[str, int]:
        now = int(time.time())
        ttl = self.ttl_seconds if remember else min(self.ttl_seconds, 8 * 60 * 60)
        payload = {
            "sub": username,
            "iat": now,
            "exp": now + ttl,
            "nonce": secrets.token_urlsafe(12),
        }
        payload_part = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        signature = self._sign(payload_part)
        return f"{payload_part}.{signature}", ttl

    def verify_token(self, token: str | None) -> AdminUser:
        if not token or "." not in token:
            raise AdminAuthError("missing_session")
        payload_part, signature = token.rsplit(".", 1)
        expected = self._sign(payload_part)
        if not hmac.compare_digest(signature, expected):
            raise AdminAuthError("invalid_signature")
        try:
            payload = json.loads(_b64url_decode(payload_part))
        except (ValueError, json.JSONDecodeError) as exc:
            raise AdminAuthError("invalid_payload") from exc
        return self._payload_to_user(payload)

    def public_session(self, token: str | None) -> dict[str, Any]:
        user = self.verify_token(token)
        return {
            "authenticated": True,
            "username": user.username,
            "configured": self.configured,
            "insecure_default_secret": self.insecure_default_secret,
        }

    def _payload_to_user(self, payload: dict[str, Any]) -> AdminUser:
        username = str(payload.get("sub") or "")
        exp = int(payload.get("exp") or 0)
        if not username:
            raise AdminAuthError("missing_subject")
        if exp < int(time.time()):
            raise AdminAuthError("session_expired")
        if not hmac.compare_digest(username, self.username):
            raise AdminAuthError("unknown_subject")
        return AdminUser(username=username)

    def _sign(self, payload_part: str) -> str:
        digest = hmac.new(self.session_secret.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
        return _b64url_encode(digest)


def is_admin_auth_exempt_path(path: str) -> bool:
    exempt = {
        "/api/health",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/session",
    }
    return path in exempt
