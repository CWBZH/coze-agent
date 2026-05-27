import pytest

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.embedding_client import (
    EmbeddingError,
    FakeEmbeddingClient,
    OllamaBgeM3EmbeddingClient,
)


def test_fake_embedding_is_stable_and_dimensioned():
    client = FakeEmbeddingClient(dimension=8, model="bge-m3")

    first = client.embed("synthetic text")
    second = client.embed("synthetic text")

    assert first.dimension == 8
    assert first.vector == second.vector
    assert first.vector_hash == second.vector_hash
    assert first.model == "bge-m3"


def test_ollama_client_uses_fake_transport_without_network():
    def transport(payload, timeout):
        assert payload["model"] == "bge-m3"
        assert "synthetic text" in payload["prompt"]
        return {"embedding": [0.1, 0.2, 0.3]}

    client = OllamaBgeM3EmbeddingClient(base_url="http://localhost:11434", transport=transport)

    vector = client.embed("synthetic text")

    assert vector.dimension == 3
    assert vector.vector_hash


def test_ollama_error_does_not_leak_text():
    def transport(payload, timeout):
        raise RuntimeError("provider failed for SECRET_SYNTHETIC_TEXT")

    client = OllamaBgeM3EmbeddingClient(base_url="http://localhost:11434", transport=transport)

    with pytest.raises(EmbeddingError) as exc:
        client.embed("SECRET_SYNTHETIC_TEXT")

    assert "SECRET_SYNTHETIC_TEXT" not in str(exc.value)
