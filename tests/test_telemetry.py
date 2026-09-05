from __future__ import annotations

from skill_router_plugin.telemetry import routing_telemetry, telemetry_from_policy


def test_default_telemetry_is_non_assessed_and_empty():
    assert routing_telemetry() == {
        "confidence": "not_assessed",
        "original_primary": "",
        "final_primary": "",
        "fallback_applied": False,
        "fallback_reason": "",
    }


def test_fallback_telemetry_keeps_only_bounded_metadata():
    result = routing_telemetry(
        confidence="medium",
        original_primary="unknown-skill",
        final_primary="ready-skill",
        fallback_applied=True,
        fallback_reason="Preferred ready fallback.\n[unsafe marker]",
    )

    assert result["confidence"] == "medium"
    assert result["original_primary"] == "unknown-skill"
    assert result["final_primary"] == "ready-skill"
    assert result["fallback_applied"] is True
    assert "\n" not in result["fallback_reason"]
    assert "[" not in result["fallback_reason"]


def test_reason_is_removed_when_no_fallback_happened():
    result = routing_telemetry(fallback_applied=False, fallback_reason="must not persist")
    assert result["fallback_reason"] == ""


def test_unknown_confidence_is_normalized():
    assert routing_telemetry(confidence="certain")["confidence"] == "not_assessed"


def test_policy_telemetry_is_normalized():
    result = telemetry_from_policy({
        "telemetry": {
            "confidence": "high",
            "original_primary": "alpha",
            "final_primary": "beta",
            "fallback_applied": True,
            "fallback_reason": "safe fallback",
            "ignored_payload": {"prompt": "do not retain"},
        }
    })

    assert result == {
        "confidence": "high",
        "original_primary": "alpha",
        "final_primary": "beta",
        "fallback_applied": True,
        "fallback_reason": "safe fallback",
    }
