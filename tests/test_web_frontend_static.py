from pathlib import Path


def test_frontend_default_api_base_url_uses_same_origin_without_hardcoded_localhost():
    client_ts = Path("web_frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert 'import.meta.env.VITE_API_BASE_URL ?? ""' in client_ts
    assert 'http://localhost:8088' not in client_ts
    assert 'http://127.0.0.1:8088' not in client_ts


def test_dashboard_does_not_hardcode_runtime_metrics():
    dashboard_tsx = Path("web_frontend/src/views/Dashboard.tsx").read_text(encoding="utf-8")

    assert "getDashboardSummary" in dashboard_tsx
    assert 'value="126"' not in dashboard_tsx
    assert 'value="92%"' not in dashboard_tsx
    assert "店铺 565617 WebSocket 曾断开" not in dashboard_tsx
