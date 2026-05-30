from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from web_api.services.sqlite_readonly import DEFAULT_DB_PATH


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_safe_account_display(account_name: str | None) -> str:
    value = (account_name or "").strip()
    if not value:
        return ""
    match = re.search(r"(\d{7,})$", value)
    if match:
        digits = match.group(1)
        prefix = value[: match.start(1)]
        return f"{prefix}{digits[:3]}***{digits[-3:]}"
    if len(value) <= 6:
        return value[0] + "***" + value[-1]
    return value[:-6] + "***" + value[-3:]


class ShopAuthCipher:
    def __init__(self, key: bytes, insecure_storage: bool = False) -> None:
        self._key = key
        self.insecure_storage = insecure_storage

    @classmethod
    def from_env(cls) -> "ShopAuthCipher":
        key = os.environ.get("SHOP_AUTH_ENCRYPTION_KEY")
        if key:
            return cls(hashlib.sha256(key.encode("utf-8")).digest(), insecure_storage=False)
        return cls(hashlib.sha256(b"dev-insecure-shop-auth-key").digest(), insecure_storage=True)

    def _stream(self, nonce: bytes, length: int) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < length:
            output.extend(hashlib.sha256(self._key + nonce + counter.to_bytes(4, "big")).digest())
            counter += 1
        return bytes(output[:length])

    def encrypt(self, plaintext: str | None) -> str:
        raw = (plaintext or "").encode("utf-8")
        nonce = os.urandom(12)
        stream = self._stream(nonce, len(raw))
        cipher_bytes = bytes(a ^ b for a, b in zip(raw, stream))
        digest = hmac.new(self._key, raw, hashlib.sha256).digest()[:16]
        packed = b"v1:" + nonce + digest + cipher_bytes
        return base64.urlsafe_b64encode(packed).decode("ascii")

    def decrypt(self, ciphertext: str | None) -> str:
        if not ciphertext:
            return ""
        packed = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        if not packed.startswith(b"v1:") or len(packed) < 31:
            raise ValueError("invalid encrypted auth payload")
        nonce = packed[3:15]
        digest = packed[15:31]
        cipher_bytes = packed[31:]
        stream = self._stream(nonce, len(cipher_bytes))
        raw = bytes(a ^ b for a, b in zip(cipher_bytes, stream))
        expected = hmac.new(self._key, raw, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(digest, expected):
            raise ValueError("invalid encrypted auth digest")
        return raw.decode("utf-8")


@dataclass(frozen=True)
class AuthSavePayload:
    shop_id: str
    shop_name: str
    platform: str
    account_name: str
    user_id: str
    cookie_value: str
    token_value: str | None = None
    expires_at: str | None = None
    credential_mode: str = "browser_only"
    auth_state_reason: str | None = None


class ShopAuthService:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH, cipher: ShopAuthCipher | None = None) -> None:
        self.db_path = Path(db_path)
        self.cipher = cipher or ShopAuthCipher.from_env()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _normalize_credential_mode(value: str | None) -> str:
        if value in {"browser_only", "password_available"}:
            return value
        return "browser_only"

    def _ensure_channel_and_shop(self, conn: sqlite3.Connection, payload: AuthSavePayload) -> int:
        now = utc_now_iso()
        conn.execute(
            "INSERT OR IGNORE INTO channels (channel_name, description) VALUES (?, ?)",
            ("pinduoduo", "PDD"),
        )
        channel_id = int(conn.execute("SELECT id FROM channels WHERE channel_name=?", ("pinduoduo",)).fetchone()["id"])
        existing_shop = conn.execute(
            "SELECT id FROM shops WHERE channel_id=? AND shop_id=?",
            (channel_id, payload.shop_id),
        ).fetchone()
        if existing_shop is None:
            conn.execute(
                """
                INSERT INTO shops (channel_id, shop_id, shop_name, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (channel_id, payload.shop_id, payload.shop_name or payload.shop_id, now),
            )
        conn.execute(
            "UPDATE shops SET shop_name=? WHERE channel_id=? AND shop_id=?",
            (payload.shop_name or payload.shop_id, channel_id, payload.shop_id),
        )
        return int(
            conn.execute(
                "SELECT id FROM shops WHERE channel_id=? AND shop_id=?",
                (channel_id, payload.shop_id),
            ).fetchone()["id"]
        )

    def save_auth(self, payload: AuthSavePayload) -> dict[str, object]:
        now = utc_now_iso()
        safe_display = build_safe_account_display(payload.account_name)
        cookie_encrypted = self.cipher.encrypt(payload.cookie_value)
        token_encrypted = self.cipher.encrypt(payload.token_value or "") if payload.token_value else None
        expires_at = payload.expires_at or (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        credential_mode = self._normalize_credential_mode(payload.credential_mode)
        auth_state_reason = payload.auth_state_reason or "auth_saved"
        conn = self._connect()
        try:
            shop_pk = self._ensure_channel_and_shop(conn, payload)
            account_user_id = payload.user_id or payload.account_name
            existing_account = conn.execute(
                "SELECT id FROM accounts WHERE shop_id=? AND user_id=?",
                (shop_pk, account_user_id),
            ).fetchone()
            if existing_account is None:
                conn.execute(
                    """
                    INSERT INTO accounts (shop_id, user_id, username, password, cookies, status)
                    VALUES (?, ?, ?, '', NULL, 1)
                    """,
                    (shop_pk, account_user_id, payload.account_name),
                )
            conn.execute(
                """
                UPDATE accounts SET username=?, password='', cookies=NULL, status=1
                WHERE shop_id=? AND user_id=?
                """,
                (payload.account_name, shop_pk, account_user_id),
            )
            conn.execute(
                """
                INSERT INTO shop_auth
                    (shop_id, platform, account_name, auth_status, cookie_encrypted, token_encrypted,
                     safe_display, last_login_at, expires_at, credential_mode, auth_state_reason,
                     last_auth_event_at, created_at, updated_at)
                VALUES (?, ?, ?, 'auth_valid', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shop_id, platform) DO UPDATE SET
                    account_name=excluded.account_name,
                    auth_status='auth_valid',
                    cookie_encrypted=excluded.cookie_encrypted,
                    token_encrypted=excluded.token_encrypted,
                    safe_display=excluded.safe_display,
                    last_login_at=excluded.last_login_at,
                    expires_at=excluded.expires_at,
                    credential_mode=excluded.credential_mode,
                    auth_state_reason=excluded.auth_state_reason,
                    last_auth_event_at=excluded.last_auth_event_at,
                    updated_at=excluded.updated_at
                """,
                (
                    payload.shop_id,
                    payload.platform,
                    payload.account_name,
                    cookie_encrypted,
                    token_encrypted,
                    safe_display,
                    now,
                    expires_at,
                    credential_mode,
                    auth_state_reason,
                    now,
                    now,
                    now,
                ),
            )
            conn.commit()
            return self.get_auth_status(payload.shop_id, payload.platform)
        finally:
            conn.close()

    def get_auth_status(self, shop_id: str, platform: str = "pdd") -> dict[str, object]:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT shop_id, platform, account_name, auth_status, safe_display, last_login_at,
                       expires_at, credential_mode, auth_state_reason, last_auth_event_at
                FROM shop_auth WHERE shop_id=? AND platform=?
                """,
                (shop_id, platform),
            ).fetchone()
            if row is None:
                raise KeyError(shop_id)
            result = dict(row)
            result["insecure_auth_storage"] = self.cipher.insecure_storage
            return result
        finally:
            conn.close()

    def update_auth_state(
        self,
        shop_id: str,
        platform: str = "pdd",
        *,
        auth_status: str,
        auth_state_reason: str,
        credential_mode: str | None = None,
    ) -> bool:
        now = utc_now_iso()
        assignments = [
            "auth_status=?",
            "auth_state_reason=?",
            "last_auth_event_at=?",
            "updated_at=?",
        ]
        values: list[object] = [auth_status, auth_state_reason, now, now]
        if credential_mode is not None:
            assignments.append("credential_mode=?")
            values.append(self._normalize_credential_mode(credential_mode))
        values.extend([shop_id, platform])
        conn = self._connect()
        try:
            cur = conn.execute(
                f"UPDATE shop_auth SET {', '.join(assignments)} WHERE shop_id=? AND platform=?",
                values,
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def mark_auth_required(self, shop_id: str, platform: str = "pdd", reason: str = "session_expired") -> bool:
        return self.update_auth_state(
            shop_id,
            platform,
            auth_status="auth_required",
            auth_state_reason=reason,
        )
