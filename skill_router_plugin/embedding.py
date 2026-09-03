"""Loopback-only Ollama embeddings and profile-scoped vector caching."""

from __future__ import annotations

import ipaddress
import json
import math
import threading
from typing import Any, Callable
from urllib import request
from urllib.parse import urlsplit


class EmbeddingError(RuntimeError):
    """Raised when local embedding retrieval cannot be trusted."""


class _NoRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class OllamaEmbeddingClient:
    """Bounded client for one loopback-only Ollama embedding endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dimensions: int,
        timeout_seconds: float,
        keep_alive: str,
        max_response_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        parsed = urlsplit(str(base_url or ""))
        try:
            loopback_host = bool(parsed.hostname) and ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback_host = False
        if (
            parsed.scheme != "http"
            or not loopback_host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("embedding_url must be a loopback-only HTTP origin")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("embedding_url has an invalid port") from exc
        if port is None or not 1 <= port <= 65535:
            raise ValueError("embedding_url must include a valid port")
        if not str(model or "").strip():
            raise ValueError("embedding_model must not be empty")
        if isinstance(dimensions, bool) or not 1 <= int(dimensions) <= 65_536:
            raise ValueError("embedding_dimensions is out of bounds")
        hostname = parsed.hostname or ""
        self.base_url = f"http://[{hostname}]:{port}" if ":" in hostname else f"http://{hostname}:{port}"
        self.model = str(model).strip()[:200]
        self.dimensions = int(dimensions)
        self.timeout_seconds = max(0.05, min(float(timeout_seconds), 30.0))
        self.keep_alive = str(keep_alive or "5m").strip()[:32] or "5m"
        self.max_response_bytes = max(1024, min(int(max_response_bytes), 64 * 1024 * 1024))
        self._opener = request.build_opener(request.ProxyHandler({}), _NoRedirectHandler())

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a bounded batch and validate the complete response."""
        if not texts:
            return []
        safe_texts = [str(text)[:16_000] for text in texts]
        payload = json.dumps({
            "model": self.model,
            "input": safe_texts,
            "keep_alive": self.keep_alive,
        }).encode("utf-8")
        req = request.Request(
            self.base_url + "/api/embed",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(req, timeout=self.timeout_seconds) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None and int(declared) > self.max_response_bytes:
                    raise EmbeddingError("embedding response exceeds size limit")
                raw = response.read(self.max_response_bytes + 1)
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"embedding request failed: {type(exc).__name__}") from exc
        if len(raw) > self.max_response_bytes:
            raise EmbeddingError("embedding response exceeds size limit")
        try:
            body = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise EmbeddingError("embedding response is not valid JSON") from exc
        vectors = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(safe_texts):
            raise EmbeddingError("embedding response count mismatch")
        output: list[list[float]] = []
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                raise EmbeddingError("embedding response dimension mismatch")
            try:
                converted = [float(value) for value in vector]
            except (TypeError, ValueError) as exc:
                raise EmbeddingError("embedding response contains a non-number") from exc
            if not all(math.isfinite(value) for value in converted):
                raise EmbeddingError("embedding response contains a non-finite number")
            output.append(converted)
        return output


_CACHE_KEY = "router.embedding_cache"
_CACHE_VERSION = 1
_CATALOG_LOCKS_GUARD = threading.Lock()
_CATALOG_LOCKS: dict[tuple[int, str], threading.Lock] = {}


def _catalog_lock_for(state: Any, profile_scope: str) -> threading.Lock:
    """Share one build lock across router instances using the same state."""
    key = (id(state), profile_scope)
    with _CATALOG_LOCKS_GUARD:
        lock = _CATALOG_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _CATALOG_LOCKS[key] = lock
        return lock


class EmbeddingCatalogRouter:
    """Rank tasks against one profile's cached catalog embeddings."""

    def __init__(
        self,
        ctx: Any,
        profile: Any,
        *,
        client_factory: Callable[..., Any] = OllamaEmbeddingClient,
    ) -> None:
        self.ctx = ctx
        self.profile = profile
        self.client_factory = client_factory
        self._catalog_lock = _catalog_lock_for(
            ctx.state,
            str(getattr(profile, "scope_token", ""))[:200],
        )

    def rank(
        self,
        task: str,
        entries: list[dict[str, Any]],
        *,
        catalog_hash: str,
    ) -> dict[str, float]:
        """Return cosine scores, building only missing profile-local vectors."""
        usable = [
            entry for entry in entries
            if isinstance(entry, dict) and str(entry.get("name") or "").strip()
        ]
        if not usable:
            return {}
        settings = self._settings()
        client = self.client_factory(**settings["client"])
        with self._catalog_lock:
            cache = self._load_cache(settings["fingerprint"])
            cached_entries = cache.get("entries")
            if not isinstance(cached_entries, dict):
                cached_entries = {}
            current_names = {str(entry.get("name") or "").strip() for entry in usable}
            vectors: dict[str, dict[str, Any]] = {}
            missing: list[dict[str, Any]] = []
            for entry in usable:
                name = str(entry.get("name") or "").strip()
                content_hash = str(entry.get("content_hash") or "")[:128]
                cached = cached_entries.get(name)
                vector = cached.get("vector") if isinstance(cached, dict) else None
                if (
                    isinstance(cached, dict)
                    and cached.get("content_hash") == content_hash
                    and self._valid_vector(vector, settings["dimensions"])
                ):
                    vectors[name] = {
                        "content_hash": content_hash,
                        "vector": vector,
                    }
                else:
                    missing.append(entry)
            batch_size = settings["batch_size"]
            for start in range(0, len(missing), batch_size):
                batch = missing[start:start + batch_size]
                texts = [self._document(entry) for entry in batch]
                embedded = client.embed(texts)
                if len(embedded) != len(batch):
                    raise EmbeddingError("embedding response count mismatch")
                for entry, vector in zip(batch, embedded):
                    normalized = self._normalize(vector, settings["dimensions"])
                    name = str(entry.get("name") or "").strip()
                    vectors[name] = {
                        "content_hash": str(entry.get("content_hash") or "")[:128],
                        "vector": normalized,
                    }
            vectors = {name: value for name, value in vectors.items() if name in current_names}
            self.ctx.state.set(_CACHE_KEY, {
                "version": _CACHE_VERSION,
                "profile": str(getattr(self.profile, "name", "custom"))[:100],
                "profile_scope": str(getattr(self.profile, "scope_token", ""))[:200],
                "catalog_hash": str(catalog_hash or "")[:128],
                "config_fingerprint": settings["fingerprint"],
                "entries": vectors,
            })

        query_vectors = client.embed([str(task or "")[:16_000]])
        if len(query_vectors) != 1:
            raise EmbeddingError("embedding query response count mismatch")
        query = self._normalize(query_vectors[0], settings["dimensions"])
        return {
            name: max(-1.0, min(1.0, sum(a * b for a, b in zip(query, value["vector"]))))
            for name, value in vectors.items()
        }

    def cache_status(self) -> dict[str, Any]:
        """Return non-sensitive profile cache diagnostics."""
        settings = self._settings()
        cache = self._load_cache(settings["fingerprint"])
        entries = cache.get("entries")
        return {
            "entries": len(entries) if isinstance(entries, dict) else 0,
            "catalog_hash": str(cache.get("catalog_hash") or "")[:12],
            "model": settings["client"]["model"],
            "dimensions": settings["dimensions"],
        }

    def _settings(self) -> dict[str, Any]:
        base_url = str(self.ctx.get_config("embedding_url", "http://127.0.0.1:11436") or "")
        model = str(self.ctx.get_config("embedding_model", "qwen3-embedding:0.6b") or "")
        dimensions = _bounded_int(
            self.ctx.get_config("embedding_dimensions", 1024), 1, 65_536, 1024
        )
        timeout = _bounded_float(
            self.ctx.get_config("embedding_timeout_seconds", 5.0), 0.05, 30.0, 5.0
        )
        keep_alive = str(self.ctx.get_config("embedding_keep_alive", "5m") or "5m")[:32]
        batch_size = _bounded_int(
            self.ctx.get_config("embedding_batch_size", 32), 1, 128, 32
        )
        fingerprint = _stable_hash({
            "url": base_url,
            "model": model,
            "dimensions": dimensions,
        })
        return {
            "client": {
                "base_url": base_url,
                "model": model,
                "dimensions": dimensions,
                "timeout_seconds": timeout,
                "keep_alive": keep_alive,
            },
            "dimensions": dimensions,
            "batch_size": batch_size,
            "fingerprint": fingerprint,
        }

    def _load_cache(self, fingerprint: str) -> dict[str, Any]:
        try:
            value = self.ctx.state.get(_CACHE_KEY, default={})
        except Exception:
            return {}
        if not isinstance(value, dict):
            return {}
        if value.get("version") != _CACHE_VERSION:
            return {}
        if value.get("profile_scope") != getattr(self.profile, "scope_token", None):
            return {}
        if value.get("config_fingerprint") != fingerprint:
            return {}
        return value

    @staticmethod
    def _document(entry: dict[str, Any]) -> str:
        name = " ".join(str(entry.get("name") or "").split())[:200]
        description = " ".join(str(entry.get("description") or "").split())[:1000]
        return f"Skill name: {name}. {description}"

    @staticmethod
    def _valid_vector(value: Any, dimensions: int) -> bool:
        return (
            isinstance(value, list)
            and len(value) == dimensions
            and all(isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item) for item in value)
            and any(float(item) != 0.0 for item in value)
        )

    @classmethod
    def _normalize(cls, value: Any, dimensions: int) -> list[float]:
        if not cls._valid_vector(value, dimensions):
            raise EmbeddingError("embedding vector is invalid")
        vector = [float(item) for item in value]
        norm = math.sqrt(sum(item * item for item in vector))
        if not math.isfinite(norm) or norm <= 0.0:
            raise EmbeddingError("embedding vector has zero norm")
        return [item / norm for item in vector]


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounded_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if not math.isfinite(parsed):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _stable_hash(value: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
