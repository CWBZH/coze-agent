"""Explicit Ollama/fake embedding smoke for internal RAG."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # noqa: F401 - avoids existing import cycle in tests.
from Message.workflow.embedding_client import EmbeddingError, FakeEmbeddingClient, OllamaBgeM3EmbeddingClient
from Message.workflow.rag_types import stable_content_hash


DEFAULT_TEXT = "synthetic embedding smoke text"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run metadata-only embedding smoke.")
    parser.add_argument("--provider", choices=["fake", "ollama"], default="fake")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--model", default="bge-m3")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--dimension", type=int)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def run_smoke(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    calls_ollama = args.provider == "ollama"
    client = (
        OllamaBgeM3EmbeddingClient(base_url=args.base_url, model=args.model, timeout=args.timeout)
        if calls_ollama
        else FakeEmbeddingClient(dimension=args.dimension or 1024, model=args.model)
    )
    try:
        vector = client.embed(args.text)
        dimension_ok = args.dimension is None or vector.dimension == args.dimension
        status = "ok" if dimension_ok else "dimension_mismatch"
        return (
            {
                "status": status,
                "provider": args.provider,
                "model": vector.model,
                "dimension": vector.dimension,
                "vector_hash": vector.vector_hash,
                "text_hash": stable_content_hash(args.text)[:16],
                "calls_ollama": calls_ollama,
                "error_type": "" if status == "ok" else "dimension_mismatch",
            },
            0 if status == "ok" else 1,
        )
    except EmbeddingError as exc:
        return (
            {
                "status": "error",
                "provider": args.provider,
                "model": args.model,
                "dimension": 0,
                "vector_hash": "",
                "text_hash": stable_content_hash(args.text)[:16],
                "calls_ollama": calls_ollama,
                "error_type": type(exc).__name__,
            },
            1,
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload, code = run_smoke(args)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered if args.json_only else "internal_rag_embedding_smoke: " + rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

