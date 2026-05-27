from pathlib import Path


def test_frontend_default_api_base_url_uses_ipv4_loopback():
    client_ts = Path("web_frontend/src/api/client.ts").read_text(encoding="utf-8")
    env_local = Path("web_frontend/.env.local").read_text(encoding="utf-8")

    assert 'http://127.0.0.1:8088' in client_ts
    assert 'http://localhost:8088' not in client_ts
    assert "VITE_API_BASE_URL=http://127.0.0.1:8088" in env_local
    assert "localhost:8090" not in env_local
