from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

from skill_router_plugin.events import (
    ALLOWED_EVENTS,
    EVENT_STATE_KEY,
    EVENT_STATE_VERSION,
    MAX_EVENTS,
    SkillRouterEvents,
)
from skill_router_plugin.profile_identity import ProfileIdentity


class State:
    def __init__(self, values=None):
        self.values = deepcopy(values or {})

    def get(self, key, default=None):
        return deepcopy(self.values.get(key, default))

    def set(self, key, value):
        self.values[key] = deepcopy(value)


class Ctx:
    def __init__(self, state=None):
        self.state = state or State()


def events(ctx=None, *, name="default", scope="home-v1:default"):
    return SkillRouterEvents(ctx or Ctx(), ProfileIdentity(name, scope))


def test_record_persists_only_scoped_technical_fields():
    ctx = Ctx()
    log = events(ctx)

    log.record(
        "skill_detected",
        skill_name="  github\nreview  ",
        result="  added  ",
        readiness="ready\x00now",
        content="not persisted",
        prompt="not persisted",
        error="not persisted",
    )

    state = ctx.state.values[EVENT_STATE_KEY]
    assert state["version"] == EVENT_STATE_VERSION
    assert state["profile"] == "default"
    assert state["profile_scope"] == "home-v1:default"
    assert state["entries"] == [{
        "timestamp": state["entries"][0]["timestamp"],
        "event": "skill_detected",
        "skill_name": "github review",
        "result": "added",
        "readiness": "",
    }]


def test_history_is_bounded_to_fifty_newest_entries():
    ctx = Ctx()
    log = events(ctx)

    for index in range(MAX_EVENTS + 12):
        log.record("skill_updated", skill_name=f"skill-{index}", result="changed")

    recent = log.recent(50)
    assert len(recent) == MAX_EVENTS
    assert recent[0]["skill_name"] == "skill-12"
    assert recent[-1]["skill_name"] == "skill-61"
    assert log.recent(500) == recent
    assert log.recent(0) == [recent[-1]]


def test_scope_mismatch_is_hidden_and_replaced_on_record():
    shared = State()
    source = events(Ctx(shared), name="same", scope="home-v1:first")
    source.record("skill_detected", skill_name="foreign")
    target = events(Ctx(shared), name="same", scope="home-v1:second")

    assert target.recent() == []
    assert target.last() is None
    assert target.render() == "Skill Router Events\n\nNo events."

    target.record("skill_detected", skill_name="local")

    state = shared.values[EVENT_STATE_KEY]
    assert state["profile_scope"] == "home-v1:second"
    assert [entry["skill_name"] for entry in state["entries"]] == ["local"]


def test_invalid_scope_token_fails_closed_without_writing():
    ctx = Ctx()
    log = events(ctx, scope="")

    log.record("skill_detected", skill_name="ignored")

    assert log.recent() == []
    assert EVENT_STATE_KEY not in ctx.state.values


def test_corrupt_state_fails_safely_and_valid_records_are_normalized():
    corrupt_values = [
        "broken",
        {"version": 999, "profile_scope": "home-v1:default", "entries": []},
        {"version": EVENT_STATE_VERSION, "profile_scope": "home-v1:default", "entries": "broken"},
    ]
    for corrupt in corrupt_values:
        log = events(Ctx(State({EVENT_STATE_KEY: corrupt})))
        assert log.recent() == []
        assert log.last() is None

    forbidden_marker = "unwanted-payload-marker"
    ctx = Ctx(State({
        EVENT_STATE_KEY: {
            "version": EVENT_STATE_VERSION,
            "profile": "default",
            "profile_scope": "home-v1:default",
            "entries": [
                None,
                {"event": "not_allowed", "timestamp": "now", "skill_name": forbidden_marker},
                {
                    "timestamp": "2026-01-02T03:04:05+00:00",
                    "event": "skill_updated",
                    "skill_name": "safe",
                    "result": "changed",
                    "readiness": "ready",
                    "content": forbidden_marker,
                },
            ],
        },
    }))
    normalized = events(ctx).recent()
    assert normalized == [{
        "timestamp": "2026-01-02T03:04:05+00:00",
        "event": "skill_updated",
        "skill_name": "safe",
        "result": "changed",
        "readiness": "ready",
    }]
    assert forbidden_marker not in repr(normalized)


def test_only_allowed_events_are_recorded_and_strings_are_bounded():
    ctx = Ctx()
    log = events(ctx)

    log.record("catalog_content", skill_name="ignored")
    for event in ALLOWED_EVENTS:
        log.record(
            event,
            skill_name="s" * 300,
            result="r" * 100,
            readiness="q" * 60,
        )

    entries = log.recent()
    assert {entry["event"] for entry in entries} == ALLOWED_EVENTS
    assert all(len(entry["skill_name"]) == 200 for entry in entries)
    assert all(entry["result"] == "" for entry in entries)
    assert all(entry["readiness"] == "" for entry in entries)


def test_render_has_heading_concise_labels_and_limit():
    ctx = Ctx()
    log = events(ctx)
    log.record("skill_detected", skill_name="alpha", result="added", readiness="ready")
    log.record("skill_updated", skill_name="beta", result="changed", readiness="setup_required")
    log.record("skill_removed", skill_name="gamma", result="removed")
    log.record("skill_refresh_failed", result="failed")

    output = log.render(4)

    assert output.startswith("Skill Router Events\n\n")
    assert "Detected: alpha (added, ready)" in output
    assert "Updated: beta (changed, setup_required)" in output
    assert "Removed: gamma (removed)" in output
    assert "Refresh failed (failed)" in output
    assert "Detected: alpha" not in log.render(3)
    assert log.last()["event"] == "skill_refresh_failed"


def test_payload_content_and_errors_never_leak_to_state_or_output():
    forbidden_marker = "unwanted-prompt-marker"
    ctx = Ctx()
    log = events(ctx)

    log.record(
        "skill_refresh_failed",
        result="failed",
        content=forbidden_marker,
        prompt=forbidden_marker,
        secrets={"token": forbidden_marker},
        error=RuntimeError(forbidden_marker),
        errors=[forbidden_marker],
    )

    assert forbidden_marker not in repr(ctx.state.values)
    assert forbidden_marker not in repr(log.recent())
    assert forbidden_marker not in log.render()
    assert set(log.last()) == {"timestamp", "event", "skill_name", "result", "readiness"}


def test_concurrent_records_remain_bounded_and_well_formed():
    ctx = Ctx()
    log = events(ctx)

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(
            lambda index: log.record("skill_updated", skill_name=f"skill-{index}", result="changed"),
            range(200),
        ))

    entries = log.recent()
    assert len(entries) == MAX_EVENTS
    assert all(set(entry) == {"timestamp", "event", "skill_name", "result", "readiness"} for entry in entries)
    assert len({entry["skill_name"] for entry in entries}) == MAX_EVENTS
