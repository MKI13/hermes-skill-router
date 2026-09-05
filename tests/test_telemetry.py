from __future__ import annotations

from copy import deepcopy
import json

import pytest

from skill_router_plugin.telemetry import (
    normalize_routing_telemetry,
    routing_telemetry,
    summarize_routing_telemetry,
    telemetry_for_recommendations,
    telemetry_from_policy,
    telemetry_lines,
    telemetry_summary_text,
)


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
    assert result["fallback_reason"] == "unspecified"


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
            "fallback_reason": "ready_within_margin",
            "ignored_payload": {"prompt": "do not retain"},
        }
    })
    assert result == {
        "confidence": "high",
        "original_primary": "alpha",
        "final_primary": "beta",
        "fallback_applied": True,
        "fallback_reason": "ready_within_margin",
    }


@pytest.mark.parametrize("value", [None, [], {}, 1, "false", "true", False])
def test_fallback_requires_a_real_boolean(value):
    result = routing_telemetry(
        original_primary="alpha", final_primary="beta", fallback_applied=value,
        fallback_reason="policy_replacement",
    )
    assert result["fallback_applied"] is False
    assert result["fallback_reason"] == ""


@pytest.mark.parametrize("value", [None, [], {}, 12, "", "alpha\nbeta", "[injected]", "x" * 121])
def test_invalid_names_and_arbitrary_objects_are_not_coerced(value):
    result = normalize_routing_telemetry({
        "original_primary": value, "final_primary": value, "confidence": [],
    })
    assert result == routing_telemetry()


def test_free_text_cannot_escape_through_the_reason_field():
    marker = "private user message with a configured credential value"
    result = normalize_routing_telemetry({
        "confidence": "medium", "original_primary": "alpha", "final_primary": "beta",
        "fallback_applied": True, "fallback_reason": marker,
        "prompt": marker, "config": {"value": marker}, "tool_payload": marker,
    })
    assert marker not in json.dumps(result)
    assert marker not in "\n".join(telemetry_lines(result))
    assert result["fallback_reason"] == "unspecified"
    assert len(result) == 5


@pytest.mark.parametrize("value", [None, [], {}, routing_telemetry()])
def test_legacy_and_missing_metadata_stays_unobserved_on_every_reload(value):
    recommended = [{"name": "alpha", "role": "primary"}]
    first = telemetry_for_recommendations(value, recommended)
    second = telemetry_for_recommendations(first, recommended)
    assert first == second == routing_telemetry()
    report = summarize_routing_telemetry([{"routing_telemetry": second}])
    assert report["observed"] == 0
    assert report["unobserved"] == 1


def test_inconsistent_cached_final_primary_does_not_claim_a_successful_fallback():
    raw = routing_telemetry(
        confidence="high", original_primary="alpha", final_primary="beta",
        fallback_applied=True, fallback_reason="ready_within_margin",
    )
    actual = [{"name": "gamma", "role": "primary"}]
    result = telemetry_for_recommendations(raw, actual)
    assert result["final_primary"] == "gamma"
    assert result["confidence"] == "not_assessed"
    assert result["fallback_applied"] is False


def test_normalization_is_idempotent_and_does_not_mutate_inputs():
    raw = {
        "confidence": "medium", "original_primary": "alpha", "final_primary": "beta",
        "fallback_applied": True, "fallback_reason": "policy_replacement", "extra": [1],
    }
    before = deepcopy(raw)
    normalized = normalize_routing_telemetry(raw)
    assert normalize_routing_telemetry(normalized) == normalized
    assert raw == before


def test_equal_or_empty_primaries_are_not_fallbacks():
    for first, last in (("alpha", "alpha"), ("", "alpha"), ("alpha", "")):
        result = routing_telemetry(original_primary=first, final_primary=last, fallback_applied=True)
        assert result["fallback_applied"] is False
        assert result["fallback_reason"] == ""


def test_summary_is_bounded_and_uses_only_finalized_assessable_quality():
    metadata = routing_telemetry(
        confidence="high", original_primary="alpha", final_primary="beta",
        fallback_applied=True, fallback_reason="ready_within_margin",
    )
    entries = [{"routing_telemetry": metadata, "finalized": True,
                "quality": {"assessable": True, "score": 0.8}}] * 1001
    entries += [{"routing_telemetry": metadata, "finalized": False,
                 "quality": {"assessable": True, "score": 1.0}}]
    original = deepcopy(entries)
    report = summarize_routing_telemetry(entries)
    assert report["observed"] == report["fallbacks"] == 1000
    assert report["cohorts"]["fallback"]["assessed"] == 999
    assert report["cohorts"]["fallback"]["mean_quality"] == 0.8
    assert entries == original
    assert "Observational only" in telemetry_summary_text(entries)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -1, 2, True, "1", None, 10 ** 1000])
def test_invalid_quality_values_do_not_inflate_telemetry_cohorts(score):
    entries = [{
        "routing_telemetry": routing_telemetry(confidence="high", final_primary="alpha"),
        "finalized": True, "quality": {"assessable": True, "score": score},
    }]
    group = summarize_routing_telemetry(entries)["cohorts"]["no_fallback"]
    assert group["assessed"] == 0
    assert group["mean_quality"] is None
