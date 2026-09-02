from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError

import pytest

from skill_router_plugin import openviking as openviking_module
from skill_router_plugin.openviking import OpenVikingBridge, _validate_base_url


class Ctx:
    profile_name = "research"

    def __init__(self, settings=None):
        self.settings = settings or {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)


def test_sync_uses_profile_scoped_mirror_name_and_tracks_hash(monkeypatch):
    bridge = OpenVikingBridge(Ctx())
    requests = []

    def request(method, path, body=None, **kwargs):
        requests.append((method, path, body, kwargs))
        if method == "GET":
            return {"skills": []}
        return {}

    monkeypatch.setattr(bridge, "_request", request)
    records = [{
        "name": "github:workflow",
        "description": "Manage pull requests.",
        "content": "---\nname: workflow\n---\n# Workflow",
        "content_hash": "abc",
    }]
    entries = [{"name": "github:workflow"}]

    report = bridge.sync_skills(records, entries)

    assert report["enabled"] is True
    assert report["synced"] == 1
    assert report["deleted"] == 0
    assert report["failed"] == []
    assert len(report["owned_names"]) == 1
    assert entries[0]["openviking_name"].startswith("hermes-research-github-workflow-")
    assert entries[0]["openviking_hash"] == "abc"
    post = next(call for call in requests if call[0] == "POST")
    assert post[1] == "/api/v1/skills"
    assert "Canonical Hermes skill name: `github:workflow`" in post[2]["data"]


def test_sync_deletes_only_previously_owned_stale_mirrors(monkeypatch):
    bridge = OpenVikingBridge(Ctx())
    requests = []

    def request(method, path, body=None, **kwargs):
        requests.append((method, path, body))
        if method == "GET":
            return {"skills": [{"name": "old-owned"}, {"name": "user-skill"}]}
        return {}

    monkeypatch.setattr(bridge, "_request", request)

    report = bridge.sync_skills([], [], previous_owned={"old-owned"})

    assert report["deleted"] == 1
    assert report["owned_names"] == []
    assert ("DELETE", "/api/v1/skills/old-owned", None) in requests
    assert all("user-skill" not in path for _method, path, _body in requests)


def test_post_conflict_retries_as_idempotent_put(monkeypatch):
    bridge = OpenVikingBridge(Ctx())
    methods = []

    def request(method, path, body=None, **kwargs):
        methods.append(method)
        if method == "GET":
            return {"skills": []}
        if method == "POST":
            raise RuntimeError("OpenViking HTTP 409: already exists")
        return {}

    monkeypatch.setattr(bridge, "_request", request)
    record = {
        "name": "github",
        "description": "GitHub",
        "content": "# GitHub",
        "content_hash": "abc",
    }
    report = bridge.sync_skills([record], [{"name": "github"}])

    assert report["failed"] == []
    assert methods == ["GET", "POST", "PUT"]


def test_find_maps_only_router_owned_openviking_skills(monkeypatch):
    bridge = OpenVikingBridge(Ctx())
    monkeypatch.setattr(
        bridge,
        "_request",
        lambda *args, **kwargs: {
            "skills": [
                {"name": "hermes-research-github-123", "score": 0.91},
                {"name": "unrelated-user-skill", "score": 0.99},
            ]
        },
    )

    scores = bridge.find_scores("open a pull request", [{
        "name": "github",
        "openviking_name": "hermes-research-github-123",
    }])

    assert scores == {"github": 0.91}


def test_plan_uri_expands_the_active_profile(monkeypatch):
    bridge = OpenVikingBridge(Ctx())
    requests = []
    monkeypatch.setattr(
        bridge,
        "_request",
        lambda method, path, body=None, **kwargs: requests.append((method, path, body)) or {},
    )

    assert bridge.write_plan("# Plan") is True
    assert requests[0][2]["uri"] == "viking://~/resources/hermes-skill-router/research/plan.md"


def test_url_validation_blocks_metadata_and_insecure_remote_credentials():
    assert _validate_base_url("http://127.0.0.1:1933", has_credentials=True) == "http://127.0.0.1:1933"
    with pytest.raises(ValueError, match="blocked address"):
        _validate_base_url("http://169.254.169.254", has_credentials=False)
    with pytest.raises(ValueError, match="require HTTPS"):
        _validate_base_url("http://8.8.8.8:1933", has_credentials=True)
    with pytest.raises(ValueError, match="path, query, or fragment"):
        _validate_base_url("https://example.com/path", has_credentials=False)


def test_request_rejects_oversized_response(monkeypatch):
    bridge = OpenVikingBridge(Ctx())

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b"x" * limit

    class Opener:
        def open(self, request, timeout):
            return Response()

    monkeypatch.setattr(openviking_module, "build_opener", lambda *handlers: Opener())

    with pytest.raises(RuntimeError, match="exceeds 2 MiB"):
        bridge._request("GET", "/api/v1/skills", timeout=1)


def test_request_reports_redirect_without_following_it(monkeypatch):
    bridge = OpenVikingBridge(Ctx())

    class Opener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 302, "redirect blocked", {}, BytesIO(b"moved"))

    monkeypatch.setattr(openviking_module, "build_opener", lambda *handlers: Opener())

    with pytest.raises(RuntimeError, match="HTTP 302"):
        bridge._request("GET", "/api/v1/skills", timeout=1)


def test_disabled_openviking_fails_open_without_requests(monkeypatch):
    bridge = OpenVikingBridge(Ctx({"openviking_enabled": False}))
    monkeypatch.setattr(bridge, "_request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))

    assert bridge.find_scores("task", []) == {}
    assert bridge.sync_skills([], []) == {
        "enabled": False,
        "synced": 0,
        "deleted": 0,
        "failed": [],
        "owned_names": [],
    }
    assert bridge.write_plan("plan") is False
