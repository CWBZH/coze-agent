"""Embedding clients for internal RAG.

Real Ollama calls are available only when a caller explicitly constructs the
Ollama client. Tests and acceptance scripts default to ``FakeEmbeddingClient``.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol

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


class DoubaoEmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        endpoint: str = "auto",
        timeout: float = 20.0,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.endpoint = str(endpoint or "auto").strip().lower()
        self.timeout = float(timeout)
        self._transport = transport

    def embed(self, text: str) -> EmbeddingVector:
        vectors = self.embed_batch([text])
        if not vectors:
            raise EmbeddingError("embedding provider returned no vector")
        return vectors[0]

    def embed_batch(self, texts: list[str]) -> list[EmbeddingVector]:
        if not texts:
            return []
        if self._uses_multimodal_endpoint():
            return [self._embed_multimodal(text) for text in texts]

        payload: dict[str, object] = {"model": self.model, "input": texts}
        try:
            data = self._transport(payload, self.timeout) if self._transport else self._post_json("/embeddings", payload)
            rows = data.get("data")
            if not isinstance(rows, list):
                raise EmbeddingError("embedding provider returned no rows")
            vectors: list[EmbeddingVector] = []
            for row in sorted(rows, key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0):
                raw_vector = row.get("embedding") if isinstance(row, dict) else None
                if not isinstance(raw_vector, list):
                    raise EmbeddingError("embedding provider returned no vector")
                vector = [float(value) for value in raw_vector]
                vectors.append(EmbeddingVector(model=self.model, dimension=len(vector), vector=vector))
            if len(vectors) != len(texts):
                raise EmbeddingError("embedding provider returned mismatched vector count")
            return vectors
        except EmbeddingError:
            raise
        except Exception as exc:  # noqa: BLE001 - sanitize all provider failures.
            raise EmbeddingError(f"embedding request failed: {type(exc).__name__}") from exc

    def _uses_multimodal_endpoint(self) -> bool:
        if self.endpoint in {"multimodal", "embeddings/multimodal", "/embeddings/multimodal"}:
            return True
        if self.endpoint in {"text", "embeddings", "/embeddings"}:
            return False
        return "vision" in self.model.lower() or "multimodal" in self.model.lower()

    def _embed_multimodal(self, text: str) -> EmbeddingVector:
        payload: dict[str, object] = {
            "model": self.model,
            "input": [
                {
                    "type": "text",
                    "text": text or "",
                }
            ],
        }
        try:
            data = self._transport(payload, self.timeout) if self._transport else self._post_json("/embeddings/multimodal", payload)
            raw_vector: Any = None
            result = data.get("data")
            if isinstance(result, dict):
                raw_vector = result.get("embedding")
            elif isinstance(result, list) and result:
                first = result[0]
                raw_vector = first.get("embedding") if isinstance(first, dict) else None
            if not isinstance(raw_vector, list):
                raise EmbeddingError("embedding provider returned no vector")
            vector = [float(value) for value in raw_vector]
        except EmbeddingError:
            raise
        except Exception as exc:  # noqa: BLE001 - sanitize all provider failures.
            raise EmbeddingError(f"embedding request failed: {type(exc).__name__}") from exc
        return EmbeddingVector(model=self.model, dimension=len(vector), vector=vector)

    def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310 - explicit opt-in.
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise EmbeddingError(f"embedding provider HTTP error: {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise EmbeddingError(f"embedding provider unavailable: {type(exc.reason).__name__}") from exc
        if not isinstance(parsed, dict):
            raise EmbeddingError("embedding provider returned invalid response")
        return parsed

