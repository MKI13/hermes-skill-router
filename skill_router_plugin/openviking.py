"""Small fail-open OpenViking HTTP bridge for skill indexing and retrieval."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .profile_identity import ProfileIdentity

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_ERROR_BYTES = 8192
_BLOCKED_IPS = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}


class OpenVikingBridge:
    """Use released OpenViking skill/content APIs without sharing its Python env."""

    def __init__(self, ctx: Any, profile: ProfileIdentity | None = None) -> None:
        self.ctx = ctx
        if profile is None:
            name = str(getattr(ctx, "profile_name", "custom") or "custom")[:100]
            profile = ProfileIdentity(name=name, scope_token=f"legacy-test:{name}")
        self.profile = profile
        self._url_cache: dict[tuple[str, bool], str] = {}

    @property
    def enabled(self) -> bool:
        value = self.ctx.get_config("openviking_enabled", False)
        return value if isinstance(value, bool) else False

    def sync_skills(
        self,
        records: list[dict[str, Any]],
        entries: list[dict[str, Any]],
        *,
        previous_owned: set[str] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Reconcile router-owned skill mirrors without touching user-owned skills."""
        if not self.enabled:
            return {"enabled": False, "synced": 0, "deleted": 0, "failed": [], "owned_names": []}
        existing = self._existing_names()
        by_name = {str(entry.get("name")): entry for entry in entries}
        current_owned: set[str] = set()
        synced = 0
        deleted = 0
        failed: list[str] = []
        for record in records:
            if should_stop is not None and should_stop():
                failed.append("sync-cancelled")
                break
            entry = by_name.get(record["name"])
            if entry is None:
                continue
            ov_name = str(entry.get("openviking_name") or self._mirror_name(record["name"]))
            entry["openviking_name"] = ov_name
            owned_before = ov_name in set(previous_owned or ())
            if ov_name in existing and not owned_before:
                failed.append(f"{record['name']}: mirror-name-conflict")
                continue
            if owned_before:
                current_owned.add(ov_name)
            if entry.get("openviking_hash") == record.get("content_hash") and ov_name in existing:
                continue
            mirrored = self._mirror_skill(record, ov_name)
            path = f"/api/v1/skills/{quote(ov_name, safe='')}"
            try:
                if ov_name in existing:
                    self._request("PUT", path, {"data": mirrored, "wait": False}, timeout=min(self._timeout(), 10.0))
                else:
                    self._request(
                        "POST",
                        "/api/v1/skills",
                        {"data": mirrored, "wait": False},
                        timeout=min(self._timeout(), 10.0),
                    )
                    existing.add(ov_name)
                    current_owned.add(ov_name)
                entry["openviking_hash"] = record.get("content_hash")
                synced += 1
            except Exception as exc:
                failed.append(f"{record['name']}: {type(exc).__name__}: {exc}")

        retained_owned = set(previous_owned or ()) | current_owned
        if not failed:
            for stale_name in sorted(set(previous_owned or ()) - current_owned):
                try:
                    self._request(
                        "DELETE",
                        f"/api/v1/skills/{quote(stale_name, safe='')}",
                        timeout=min(self._timeout(), 10.0),
                    )
                    retained_owned.discard(stale_name)
                    deleted += 1
                except Exception as exc:
                    if "HTTP 404" in str(exc):
                        retained_owned.discard(stale_name)
                        deleted += 1
                    else:
                        failed.append(f"delete {stale_name}: {type(exc).__name__}: {exc}")
        return {
            "enabled": True,
            "synced": synced,
            "deleted": deleted,
            "failed": failed[:50],
            "owned_names": sorted(retained_owned),
        }

    def find_scores(self, task: str, entries: list[dict[str, Any]]) -> dict[str, float]:
        """Return OpenViking retrieval scores mapped back to canonical Hermes names."""
        if not self.enabled:
            return {}
        limit = self._int_setting("openviking_retrieval_limit", 12, 1, 100)
        threshold = self._float_setting("openviking_score_threshold", 0.15, 0.0, 1.0)
        try:
            payload = self._request(
                "POST",
                "/api/v1/skills/find",
                {"query": task, "limit": limit, "score_threshold": threshold},
                timeout=float(self._int_setting("openviking_routing_timeout_seconds", 3, 1, 5)),
            )
        except Exception:
            return {}
        reverse = {
            str(entry.get("openviking_name")): str(entry.get("name"))
            for entry in entries
            if entry.get("openviking_name") and entry.get("name")
        }
        hits = _find_list(payload, ("skills", "results", "items", "hits"))
        scores: dict[str, float] = {}
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            ov_name = str(hit.get("name") or hit.get("skill_name") or _uri_tail(hit.get("uri")))
            hermes_name = reverse.get(ov_name)
            if not hermes_name:
                continue
            raw_score = hit.get("score", hit.get("similarity", 0.0))
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                score = 0.0
            scores[hermes_name] = max(scores.get(hermes_name, 0.0), score)
        return scores

    def write_plan(self, plan_markdown: str) -> bool:
        """Store the generated routing artifact as an OpenViking resource file."""
        if not self.enabled:
            return False
        try:
            configured_uri = str(self.ctx.get_config(
                "openviking_plan_uri",
                "viking://~/resources/hermes-skill-router/{profile}/plan.md",
            ))
            profile_slug = self.profile.external_slug
            self._request(
                "POST",
                "/api/v1/content/write",
                {
                    "uri": _profile_scoped_uri(configured_uri, profile_slug),
                    "content": plan_markdown,
                    "mode": "replace",
                    "wait": False,
                },
                timeout=min(self._timeout(), 10.0),
            )
            return True
        except Exception:
            return False

    def _existing_names(self) -> set[str]:
        payload = self._request(
            "GET",
            "/api/v1/skills?" + urlencode({"node_limit": 10000}),
            timeout=min(self._timeout(), 5.0),
        )
        skills = _find_list(payload, ("skills", "items", "results"))
        return {
            str(item.get("name") or item.get("skill_name") or _uri_tail(item.get("uri")))
            for item in skills
            if isinstance(item, dict)
        }

    def _mirror_name(self, hermes_name: str) -> str:
        slug = re.sub(
            r"[^a-z0-9_-]+",
            "-",
            f"{self.profile.external_slug}-{hermes_name}".casefold(),
        ).strip("-_")
        digest = hashlib.sha256(
            f"{self.profile.scope_token}\0{hermes_name}".encode("utf-8")
        ).hexdigest()[:10]
        return f"hermes-{slug[:38]}-{digest}"

    def _mirror_skill(self, record: dict[str, Any], ov_name: str) -> str:
        description = str(record.get("description") or "Mirrored Hermes Agent skill.")
        description = re.sub(r"\s+", " ", description).strip()[:500]
        canonical = " ".join(str(record["name"]).split())[:200]
        original = str(record.get("content") or "")[:self._int_setting(
            "max_skill_chars", 20000, 1000, 200000
        )]
        return (
            "---\n"
            f"name: {ov_name}\n"
            f"description: {json.dumps(description, ensure_ascii=False)}\n"
            "metadata:\n"
            "  source: hermes-skill-router\n"
            f"  hermes_skill_name: {json.dumps(canonical, ensure_ascii=False)}\n"
            "---\n"
            f"# Hermes skill mirror: {canonical}\n\n"
            f"Canonical Hermes skill name: `{canonical}`. Load this name through Hermes "
            "`skill_view`; this OpenViking copy is retrieval data, not an execution path.\n\n"
            "## Original SKILL.md\n\n"
            f"{original}\n"
        )

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        api_key = os.environ.get("OPENVIKING_API_KEY", "").strip()
        account = os.environ.get("OPENVIKING_ACCOUNT", "").strip()
        user = os.environ.get("OPENVIKING_USER", "").strip()
        base_url = self._base_url(has_credentials=bool(api_key or account or user))
        url = base_url + path
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if api_key:
            headers["X-API-Key"] = api_key
        if account:
            headers["X-OpenViking-Account"] = account
        if user:
            headers["X-OpenViking-User"] = user
        request = Request(url, data=data, headers=headers, method=method)
        opener = build_opener(ProxyHandler({}), _RejectRedirects())
        try:
            with opener.open(request, timeout=timeout or self._timeout()) as response:
                raw_bytes = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(raw_bytes) > _MAX_RESPONSE_BYTES:
                    raise RuntimeError("OpenViking response exceeds 2 MiB limit")
                raw = raw_bytes.decode("utf-8")
        except HTTPError as exc:
            detail = exc.read(_MAX_ERROR_BYTES + 1)[:_MAX_ERROR_BYTES].decode(
                "utf-8", errors="replace"
            )
            raise RuntimeError(f"OpenViking HTTP {exc.code}: {detail}") from exc
        except (URLError, OSError) as exc:
            raise RuntimeError(f"OpenViking unavailable: {exc}") from exc
        if not raw:
            return {}
        parsed = json.loads(raw)
        return _unwrap(parsed)

    def _base_url(self, *, has_credentials: bool = False) -> str:
        configured = str(self.ctx.get_config("openviking_url", "") or "").strip()
        env_url = os.environ.get("OPENVIKING_URL") or os.environ.get("OPENVIKING_ENDPOINT")
        raw = configured or env_url or "http://127.0.0.1:1933"
        key = (raw, has_credentials)
        if key not in self._url_cache:
            self._url_cache[key] = _validate_base_url(raw, has_credentials=has_credentials)
        return self._url_cache[key]

    def _timeout(self) -> float:
        return float(self._int_setting("openviking_timeout_seconds", 120, 1, 600))

    def _int_setting(self, key: str, default: int, minimum: int, maximum: int) -> int:
        value = self.ctx.get_config(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            value = default
        return max(minimum, min(maximum, value))

    def _float_setting(self, key: str, default: float, minimum: float, maximum: float) -> float:
        value = self.ctx.get_config(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            value = default
        return max(minimum, min(maximum, float(value)))


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "OpenViking redirects are disabled", headers, fp)


def _profile_scoped_uri(template: str, profile_slug: str) -> str:
    if "{profile}" in template:
        return template.replace("{profile}", profile_slug)
    prefix, separator, leaf = template.rpartition("/")
    if not separator:
        return f"{template}/{profile_slug}/plan.md"
    return f"{prefix}/{profile_slug}/{leaf or 'plan.md'}"


def _validate_base_url(raw: str, *, has_credentials: bool) -> str:
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("OpenViking URL must use http or https")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("OpenViking URL must have a host and no userinfo")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("OpenViking base URL cannot contain a path, query, or fragment")
    addresses = _resolve_addresses(parsed.hostname)
    for address in addresses:
        if (
            address in _BLOCKED_IPS
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
        ):
            raise ValueError(f"OpenViking URL resolves to blocked address {address}")
    if has_credentials and parsed.scheme != "https" and not addresses.issubset(
        {address for address in addresses if address.is_loopback}
    ):
        raise ValueError("Credentialed OpenViking connections require HTTPS outside loopback")
    return raw.rstrip("/")


def _resolve_addresses(hostname: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return {ipaddress.ip_address(hostname)}
    except ValueError:
        pass
    try:
        resolved = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ValueError(f"Cannot resolve OpenViking host {hostname}: {exc}") from exc
    if not resolved:
        raise ValueError(f"Cannot resolve OpenViking host {hostname}")
    return resolved


def _unwrap(value: Any) -> Any:
    current = value
    for _ in range(3):
        if not isinstance(current, dict):
            break
        next_value = None
        for key in ("result", "data"):
            candidate = current.get(key)
            if isinstance(candidate, (dict, list)):
                next_value = candidate
                break
        if next_value is None:
            break
        current = next_value
    return current


def _find_list(value: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, list):
            return candidate
        if isinstance(candidate, dict):
            nested = _find_list(candidate, keys)
            if nested:
                return nested
    return []


def _uri_tail(value: Any) -> str:
    text = str(value or "").rstrip("/")
    return text.rsplit("/", 1)[-1] if text else ""
