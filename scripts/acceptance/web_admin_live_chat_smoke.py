"""No-send smoke runner for Web Admin Live Chat profiles."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient

from web_api.main import app


PROFILES = ("facade", "real_engine_only", "real_rag", "real_intent", "real_answer", "real_full")
REAL_PROVIDER_PROFILES = {"real_rag", "real_intent", "real_answer", "real_full"}
REQUIRED_PROVIDERS = {
    "real_rag": ("pgvector", "ollama"),
    "real_intent": ("llm",),
    "real_answer": ("llm",),
    "real_full": ("pgvector", "ollama", "llm"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Web Admin live chat no-send smoke profiles.")
    parser.add_argument("--profile", action="append", choices=PROFILES, help="Smoke profile to run. Repeatable.")
    parser.add_argument("--provider-status", action="store_true", help="Print provider configuration status.")
    parser.add_argument("--real-providers", action="store_true", help="Allow profiles that may use real provider adapters.")
    parser.add_argument("--require-real-providers", action="store_true", help="Fail when required real providers are missing.")
    parser.add_argument("--shop-id", default="323473738")
    parser.add_argument("--buyer-id", default="web-smoke-buyer")
    parser.add_argument("--message", default="这个多少钱")
    parser.add_argument("--goods-id", default="943269377110")
    parser.add_argument("--goods-name", default="脖子身体懒人素颜霜")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = TestClient(app)
    provider_status = _provider_status(client) if args.provider_status or args.real_providers or args.require_real_providers else None
    profiles = args.profile or ([] if args.provider_status else ["facade", "real_engine_only"])
    results = [_run_profile(client, args, profile, provider_status) for profile in profiles]
    failed = [
        item
        for item in results
        if item["status"] == "failed"
        or (args.require_real_providers and item.get("engine_adapter_status") == "config_missing")
    ]
    payload: dict[str, Any] = {"status": "failed" if failed else "passed"}
    if provider_status is not None:
        payload["provider_status"] = provider_status
    if results:
        payload["results"] = results
    print(json.dumps(payload, ensure_ascii=False, indent=None if args.json_only else 2))
    return 1 if failed else 0


def _provider_status(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/provider-status")
    if response.status_code != 200:
        return {"status": "failed", "reason": f"http_{response.status_code}"}
    return response.json()


def _run_profile(
    client: TestClient,
    args: argparse.Namespace,
    profile: str,
    provider_status: dict[str, Any] | None,
) -> dict[str, Any]:
    if profile in REAL_PROVIDER_PROFILES and not args.real_providers:
        return {
            "profile": profile,
            "status": "skipped",
            "reason": "real_providers_not_enabled",
            "no_send": True,
            "sends_pdd": False,
        }

    missing = _missing_required_providers(profile, provider_status)
    if args.require_real_providers and missing:
        return {
            "profile": profile,
            "status": "failed",
            "reason": "provider_config_missing",
            "missing_providers": missing,
            "no_send": True,
            "sends_pdd": False,
        }

    session_response = client.post(
        "/api/live-chat/sessions",
        json={"shop_id": args.shop_id, "buyer_id": args.buyer_id},
    )
    if session_response.status_code != 200:
        return {"profile": profile, "status": "failed", "reason": f"session_http_{session_response.status_code}"}
    session_id = session_response.json()["session_id"]
    body = {
        "shop_id": args.shop_id,
        "buyer_id": args.buyer_id,
        "message": args.message,
        "metadata": {"goods_id": args.goods_id, "goods_name": args.goods_name},
        "smoke_profile": profile,
        "no_send": True,
        **_profile_flags(profile),
    }
    message_response = client.post(f"/api/live-chat/sessions/{session_id}/messages", json=body)
    if message_response.status_code != 200:
        return {"profile": profile, "status": "failed", "reason": f"message_http_{message_response.status_code}"}
    payload = message_response.json()
    trace = payload.get("trace") or {}
    return {
        "profile": profile,
        "status": "passed",
        "engine_mode": trace.get("engine_mode"),
        "engine_adapter_status": trace.get("engine_adapter_status"),
        "real_engine_called": trace.get("real_engine_called"),
        "provider_status": trace.get("provider_status"),
        "stage_status": trace.get("stage_status"),
        "latency_ms": trace.get("latency_ms"),
        "calls_llm": trace.get("calls_llm"),
        "calls_ollama": trace.get("calls_ollama"),
        "connects_pgvector": trace.get("connects_pgvector"),
        "no_send": trace.get("no_send"),
        "sends_pdd": trace.get("sends_pdd"),
        "intent": payload.get("intent"),
        "action": payload.get("action"),
        "domain": payload.get("domain"),
    }


def _missing_required_providers(profile: str, provider_status: dict[str, Any] | None) -> list[str]:
    required = REQUIRED_PROVIDERS.get(profile, ())
    if not required:
        return []
    providers = (provider_status or {}).get("providers") or {}
    missing = []
    for provider in required:
        status = (providers.get(provider) or {}).get("status")
        if status != "configured":
            missing.append(provider)
    return missing


def _profile_flags(profile: str) -> dict[str, bool]:
    if profile == "facade":
        return {
            "use_real_engine": False,
            "use_real_pgvector": False,
            "use_real_ollama": False,
            "use_real_llm": False,
            "use_real_intent_classifier": False,
            "use_real_answer_generator": False,
        }
    if profile == "real_engine_only":
        return {
            "use_real_engine": True,
            "use_real_pgvector": False,
            "use_real_ollama": False,
            "use_real_llm": False,
            "use_real_intent_classifier": False,
            "use_real_answer_generator": False,
        }
    if profile == "real_rag":
        return {
            "use_real_engine": True,
            "use_real_pgvector": True,
            "use_real_ollama": True,
            "use_real_llm": False,
            "use_real_intent_classifier": False,
            "use_real_answer_generator": False,
        }
    if profile == "real_intent":
        return {
            "use_real_engine": True,
            "use_real_pgvector": False,
            "use_real_ollama": False,
            "use_real_llm": True,
            "use_real_intent_classifier": True,
            "use_real_answer_generator": False,
        }
    if profile == "real_answer":
        return {
            "use_real_engine": True,
            "use_real_pgvector": False,
            "use_real_ollama": False,
            "use_real_llm": True,
            "use_real_intent_classifier": False,
            "use_real_answer_generator": True,
        }
    return {
        "use_real_engine": True,
        "use_real_pgvector": True,
        "use_real_ollama": True,
        "use_real_llm": True,
        "use_real_intent_classifier": True,
        "use_real_answer_generator": True,
    }


if __name__ == "__main__":
    raise SystemExit(main())
