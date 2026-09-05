from __future__ import annotations

import json
from pathlib import Path

import pytest

from skill_router_plugin.planner import (
    DEFAULT_DETERMINISTIC_MIN_SCORE,
    DEFAULT_DETERMINISTIC_SUPPORTING_MIN_SCORE,
)
from tests.routing_golden_support import projection, route_new, route_old


FIXTURE = Path(__file__).parent / "fixtures" / "routing_golden.json"
CALIBRATION_FIXTURE = Path(__file__).parent / "fixtures" / "production_score_calibration.json"


def cases() -> list[dict]:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert document["version"] == 2
    values = document["cases"]
    assert 30 <= len(values) <= 55
    ids = [item["id"] for item in values]
    assert len(ids) == len(set(ids))
    return values


@pytest.mark.parametrize("case", cases(), ids=lambda case: case["id"])
def test_golden_deterministic_routing(case):
    assert projection(route_new(case["task"])) == case["expected"]


def metrics(router) -> dict[str, float | int]:
    values = cases()
    outputs = [(case, projection(router(case["task"]))) for case in values]
    expected_empty = [item for item in outputs if not item[0]["expected"]]
    true_empty = [item for item in expected_empty if not item[1]]
    primary_cases = [item for item in outputs if item[0]["expected"]]
    correct_primary = sum(
        next((actual["name"] for actual in item[1] if actual["role"] == "primary"), None)
        == next(expected["name"] for expected in item[0]["expected"] if expected["role"] == "primary")
        for item in primary_cases
    )
    expected_supporting = {
        (case["id"], item["name"])
        for case, _actual in outputs
        for item in case["expected"]
        if item["role"] == "supporting"
    }
    actual_supporting = {
        (case["id"], item["name"])
        for case, actual in outputs
        for item in actual
        if item["role"] == "supporting"
    }
    false_supporting = actual_supporting - expected_supporting
    return {
        "no_skill_false_positives": len(expected_empty) - len(true_empty),
        "wrong_primary": len(primary_cases) - correct_primary,
        "unnecessary_supporting": len(false_supporting),
        "no_skill_precision": len(true_empty) / max(1, len(expected_empty)),
        "primary_precision": correct_primary / max(1, len(primary_cases)),
        "supporting_false_positive_rate": len(false_supporting) / max(1, len(actual_supporting)),
    }


def test_production_score_aggregate_justifies_default_thresholds():
    calibration = json.loads(CALIBRATION_FIXTURE.read_text(encoding="utf-8"))

    assert calibration["catalog_size"] == 76
    assert max(calibration["no_skill_scores"]) < DEFAULT_DETERMINISTIC_MIN_SCORE
    assert min(calibration["intended_skill_scores"]) >= DEFAULT_DETERMINISTIC_SUPPORTING_MIN_SCORE
    assert calibration["selected_primary_threshold"] == DEFAULT_DETERMINISTIC_MIN_SCORE
    assert calibration["selected_supporting_threshold"] == DEFAULT_DETERMINISTIC_SUPPORTING_MIN_SCORE


def test_golden_quality_targets():
    result = metrics(route_new)

    assert result["no_skill_precision"] >= 0.95
    assert result["primary_precision"] >= 0.90
    assert result["supporting_false_positive_rate"] <= 0.10


def test_calibration_improves_legacy_fallback():
    before = metrics(route_old)
    after = metrics(route_new)

    assert after["no_skill_false_positives"] < before["no_skill_false_positives"]
    assert after["wrong_primary"] <= before["wrong_primary"]
    assert after["unnecessary_supporting"] < before["unnecessary_supporting"]
