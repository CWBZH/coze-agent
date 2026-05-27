"""Embedding clients for internal RAG.

Real Ollama calls are available only when a caller explicitly constructs the
Ollama client. Tests and acceptance scripts default to ``FakeEmbeddingClient``.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import Callable, Protocol

from .rag_types import EmbeddingVector, stable_content_hash


class EmbeddingError(RuntimeError):
    """Embedding failure with a sanitized message."""


class EmbeddingClient(Protocol):
    model: str

    def embed(self, text: str) -> EmbeddingVector:
        ...

    def embed_batch(self, texts: list[str]) -> list[EmbeddingVector]:
        ...


class FakeEmbeddingClient:
    def __init__(self, *, dimension: int = 1024, model: str = "bge-m3"):
        self.dimension = int(dimension)
        self.model = model

    def embed(self, text: str) -> EmbeddingVector:
        digest = stable_content_hash(text)
        values: list[float] = []
        for index in range(self.dimension):
            offset = (index * 2) % len(digest)
            raw = int(digest[offset : offset + 2], 16)
            values.append((raw / 127.5) - 1.0)
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return EmbeddingVector(model=self.model, dimension=self.dimension, vector=[value / norm for value in values])

    def embed_batch(self, texts: list[str]) -> list[EmbeddingVector]:
        return [self.embed(text) for text in texts]


Transport = Callable[[dict[str, object], float], dict[str, object]]


class OllamaBgeM3EmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "bge-m3",
        timeout: float = 15.0,
        transport: Transport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = float(timeout)
        self._transport = transport

    def embed(self, text: str) -> EmbeddingVector:
        payload: dict[str, object] = {"model": self.model, "prompt": text or ""}
        try:
            response = self._transport(payload, self.timeout) if self._transport else self._post(payload)
            raw_vector = response.get("embedding") or response.get("embeddings")
            if isinstance(raw_vector, list) and raw_vector and isinstance(raw_vector[0], list):
                raw_vector = raw_vector[0]
            if not isinstance(raw_vector, list):
                raise EmbeddingError("embedding provider returned no vector")
            vector = [float(value) for value in raw_vector]
        except EmbeddingError:
            raise
        except Exception as exc:  # noqa: BLE001 - sanitize all provider failures.
            raise EmbeddingError(f"embedding request failed: {type(exc).__name__}") from exc
        return EmbeddingVector(model=self.model, dimension=len(vector), vector=vector)

    def embed_batch(self, texts: list[str]) -> list[EmbeddingVector]:
        return [self.embed(text) for text in texts]

    def _post(self, payload: dict[str, object]) -> dict[str, object]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embeddings",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310 - explicit local opt-in.
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise EmbeddingError(f"embedding provider HTTP error: {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise EmbeddingError(f"embedding provider unavailable: {type(exc.reason).__name__}") from exc

