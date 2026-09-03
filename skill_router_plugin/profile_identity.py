"""Opaque active-profile identity for isolated Router state and mirrors."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any


@dataclass(frozen=True)
class ProfileIdentity:
    """Canonical profile label plus a non-reversible Hermes-home token."""

    name: str
    scope_token: str

    @property
    def external_slug(self) -> str:
        """Return a collision-resistant non-path identifier for external resources."""
        label = re.sub(r"[^a-z0-9_-]+", "-", self.name.casefold()).strip("-_") or "profile"
        digest = self.scope_token.rsplit(":", 1)[-1][:10]
        return f"{label}-{digest}"


def resolve_profile_identity(ctx: Any, compatibility: Any) -> ProfileIdentity:
    """Resolve the active profile without assuming any user-defined name."""
    name = str(getattr(ctx, "profile_name", "custom") or "custom")[:100]
    resolver = getattr(compatibility, "profile_scope_id", None)
    if callable(resolver):
        scope_token = str(resolver())
    else:
        digest = hashlib.sha256(f"test-profile:{name}".encode("utf-8")).hexdigest()
        scope_token = f"fallback-v1:{digest}"
    return ProfileIdentity(name=name, scope_token=scope_token)


def legacy_audit_matches_profile(raw: Any, identity: ProfileIdentity) -> bool:
    """Return whether every legacy audit entry is explicitly attributable here."""
    if identity.name == "custom" or not isinstance(raw, dict):
        return False
    entries = raw.get("entries")
    if not isinstance(entries, list) or not entries:
        return False
    return all(
        isinstance(entry, dict) and entry.get("profile") == identity.name
        for entry in entries
    )
