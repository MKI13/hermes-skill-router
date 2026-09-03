from __future__ import annotations

import json
import threading
import time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from skill_router_plugin.embedding import (
    EmbeddingCatalogRouter,
    EmbeddingError,
    OllamaEmbeddingClient,
)


class _EmbeddingHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).requests.append({"path": self.path, "payload": payload})
        vectors = [[1.0, 0.0] for _ in payload["input"]]
        body = json.dumps({"embeddings": vectors}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def test_ollama_client_embeds_batch_with_keep_alive():
    _EmbeddingHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EmbeddingHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        client = OllamaEmbeddingClient(
            base_url=f"http://127.0.0.1:{server.server_port}",
            model="qwen3-embedding:0.6b",
            dimensions=2,
            timeout_seconds=2.0,
            keep_alive="5m",
        )

        assert client.embed(["eins", "zwei"]) == [[1.0, 0.0], [1.0, 0.0]]
        assert _EmbeddingHandler.requests == [{
            "path": "/api/embed",
            "payload": {
                "model": "qwen3-embedding:0.6b",
                "input": ["eins", "zwei"],
                "keep_alive": "5m",
            },
        }]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@pytest.mark.parametrize("url", [
    "http://169.254.169.254:11434",
    "http://127.0.0.1.evil.example:11434",
    "http://localhost:11434",
    "http://user@127.0.0.1:11434",
    "http://127.0.0.1:11434/other",
    "http://127.0.0.1:11434?next=http://169.254.169.254",
    "https://127.0.0.1:11434",
])
def test_ollama_client_rejects_non_loopback_or_non_origin_urls(url):
    with pytest.raises(ValueError, match="loopback-only HTTP origin"):
        OllamaEmbeddingClient(
            base_url=url,
            model="qwen3-embedding:0.6b",
            dimensions=2,
            timeout_seconds=1.0,
            keep_alive="5m",
        )


class _RedirectHandler(BaseHTTPRequestHandler):
    followed = False

    def do_POST(self):  # noqa: N802
        if self.path == "/redirected":
            type(self).followed = True
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(302)
        self.send_header("Location", "/redirected")
        self.end_headers()

    def log_message(self, _format, *_args):
        return


def test_ollama_client_does_not_follow_redirects():
    _RedirectHandler.followed = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        client = OllamaEmbeddingClient(
            base_url=f"http://127.0.0.1:{server.server_port}",
            model="qwen3-embedding:0.6b",
            dimensions=2,
            timeout_seconds=1.0,
            keep_alive="5m",
        )
        with pytest.raises(EmbeddingError, match="request failed"):
            client.embed(["test"])
        assert _RedirectHandler.followed is False
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class _OversizedHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "2000")
        self.end_headers()
        self.wfile.write(b"x" * 2000)

    def log_message(self, _format, *_args):
        return


def test_ollama_client_rejects_oversized_responses():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OversizedHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        client = OllamaEmbeddingClient(
            base_url=f"http://127.0.0.1:{server.server_port}",
            model="qwen3-embedding:0.6b",
            dimensions=2,
            timeout_seconds=1.0,
            keep_alive="5m",
            max_response_bytes=1024,
        )
        with pytest.raises(EmbeddingError, match="exceeds size limit"):
            client.embed(["test"])
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class _SlowHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        time.sleep(0.2)
        self.send_response(200)
        self.end_headers()

    def log_message(self, _format, *_args):
        return


def test_ollama_client_has_a_bounded_timeout():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        client = OllamaEmbeddingClient(
            base_url=f"http://127.0.0.1:{server.server_port}",
            model="qwen3-embedding:0.6b",
            dimensions=2,
            timeout_seconds=0.05,
            keep_alive="5m",
        )
        started = time.monotonic()
        with pytest.raises(EmbeddingError, match="request failed"):
            client.embed(["test"])
        assert time.monotonic() - started < 0.5
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class _MalformedHandler(BaseHTTPRequestHandler):
    body = b"{}"

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = type(self).body
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


@pytest.mark.parametrize("body", [
    b'{"embeddings": []}',
    b'{"embeddings": [[1.0]]}',
    b'{"embeddings": [[NaN, 0.0]]}',
    b'not-json',
])
def test_ollama_client_rejects_malformed_embedding_responses(body):
    _MalformedHandler.body = body
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MalformedHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        client = OllamaEmbeddingClient(
            base_url=f"http://127.0.0.1:{server.server_port}",
            model="qwen3-embedding:0.6b",
            dimensions=2,
            timeout_seconds=1.0,
            keep_alive="5m",
        )
        with pytest.raises(EmbeddingError):
            client.embed(["test"])
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class _State:
    quota_bytes = 10 * 1024 * 1024

    def __init__(self):
        self.values = {}
        self.lock = threading.Lock()

    def get(self, key, default=None):
        with self.lock:
            return deepcopy(self.values.get(key, default))

    def set(self, key, value):
        with self.lock:
            self.values[key] = deepcopy(value)


class _Ctx:
    def __init__(self, state=None, settings=None):
        self.state = state or _State()
        self.settings = {"embedding_dimensions": 2, **(settings or {})}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)


class _FakeEmbeddingClient:
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def embed(self, texts):
        with self.lock:
            self.calls.append(list(texts))
        vectors = []
        for text in texts:
            normalized = text.casefold()
            if "alpha" in normalized:
                vectors.append([1.0, 0.0])
            elif "beta" in normalized:
                vectors.append([0.0, 1.0])
            else:
                vectors.append([0.7, 0.7])
        return vectors


def _entries(alpha_hash="alpha-v1"):
    return [
        {
            "name": "alpha",
            "description": "Alpha workflow.",
            "content_hash": alpha_hash,
            "content": "SECRET FULL SKILL BODY",
        },
        {
            "name": "beta",
            "description": "Beta workflow.",
            "content_hash": "beta-v1",
            "content": "ANOTHER SECRET BODY",
        },
    ]


def test_catalog_router_embeds_only_name_and_description_and_caches_by_profile():
    fake = _FakeEmbeddingClient()
    state = _State()
    profile = SimpleNamespace(name="canary", scope_token="scope:canary")
    router = EmbeddingCatalogRouter(_Ctx(state), profile, client_factory=lambda **_kwargs: fake)

    scores = router.rank("alpha request", _entries(), catalog_hash="catalog-v1")
    second = EmbeddingCatalogRouter(
        _Ctx(state), profile, client_factory=lambda **_kwargs: fake
    ).rank("beta request", _entries(), catalog_hash="catalog-v1")

    assert scores["alpha"] > scores["beta"]
    assert second["beta"] > second["alpha"]
    assert fake.calls[0] == [
        "Skill name: alpha. Alpha workflow.",
        "Skill name: beta. Beta workflow.",
    ]
    assert "SECRET" not in repr(fake.calls)
    assert fake.calls[1:] == [["alpha request"], ["beta request"]]
    persisted = state.get("router.embedding_cache")
    assert persisted["profile_scope"] == "scope:canary"
    assert persisted["catalog_hash"] == "catalog-v1"
    assert set(persisted["entries"]) == {"alpha", "beta"}


def test_catalog_router_reembeds_changed_content_hash_and_rejects_copied_profile_cache():
    fake = _FakeEmbeddingClient()
    state = _State()
    first = EmbeddingCatalogRouter(
        _Ctx(state),
        SimpleNamespace(name="one", scope_token="scope:one"),
        client_factory=lambda **_kwargs: fake,
    )
    first.rank("alpha", _entries(), catalog_hash="catalog-v1")
    first.rank("alpha", _entries("alpha-v2"), catalog_hash="catalog-v2")
    copied = EmbeddingCatalogRouter(
        _Ctx(state),
        SimpleNamespace(name="two", scope_token="scope:two"),
        client_factory=lambda **_kwargs: fake,
    )
    copied.rank("alpha", _entries("alpha-v2"), catalog_hash="catalog-v2")

    document_calls = [call for call in fake.calls if call and call[0].startswith("Skill name:")]
    assert document_calls == [
        ["Skill name: alpha. Alpha workflow.", "Skill name: beta. Beta workflow."],
        ["Skill name: alpha. Alpha workflow."],
        ["Skill name: alpha. Alpha workflow.", "Skill name: beta. Beta workflow."],
    ]
    assert state.get("router.embedding_cache")["profile_scope"] == "scope:two"


def test_catalog_router_coalesces_concurrent_catalog_embedding():
    fake = _FakeEmbeddingClient()
    original_embed = fake.embed

    def slow_embed(texts):
        if texts and texts[0].startswith("Skill name:"):
            time.sleep(0.05)
        return original_embed(texts)

    fake.embed = slow_embed
    ctx = _Ctx()
    profile = SimpleNamespace(name="canary", scope_token="scope:canary")
    barrier = threading.Barrier(8)
    errors = []

    def run():
        try:
            barrier.wait(timeout=2)
            router = EmbeddingCatalogRouter(
                ctx,
                profile,
                client_factory=lambda **_kwargs: fake,
            )
            router.rank("alpha request", _entries(), catalog_hash="catalog-v1")
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)

    workers = [threading.Thread(target=run) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=3)

    assert errors == []
    document_calls = [call for call in fake.calls if call and call[0].startswith("Skill name:")]
    assert len(document_calls) == 1
    assert len([call for call in fake.calls if call == ["alpha request"]]) == 8
