import os

from web_api.services.shop_auth_service import ShopAuthCipher, build_safe_account_display


def test_shop_auth_cipher_roundtrip_and_ciphertext_is_not_plaintext(monkeypatch):
    monkeypatch.setenv("SHOP_AUTH_ENCRYPTION_KEY", "unit-test-key")
    cipher = ShopAuthCipher.from_env()

    encrypted = cipher.encrypt("fake-cookie-value")

    assert encrypted != "fake-cookie-value"
    assert "fake-cookie-value" not in encrypted
    assert cipher.decrypt(encrypted) == "fake-cookie-value"
    assert cipher.insecure_storage is False


def test_shop_auth_cipher_uses_insecure_dev_key_when_env_missing(monkeypatch):
    monkeypatch.delenv("SHOP_AUTH_ENCRYPTION_KEY", raising=False)
    cipher = ShopAuthCipher.from_env()

    encrypted = cipher.encrypt("dev-cookie")

    assert cipher.decrypt(encrypted) == "dev-cookie"
    assert cipher.insecure_storage is True


def test_safe_account_display_excludes_sensitive_values():
    display = build_safe_account_display("seller_account_13570354888")

    assert display == "seller_account_135***888"
    assert "fake-cookie" not in display
    assert "token" not in display.lower()
    assert "password" not in display.lower()
