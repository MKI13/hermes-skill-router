#!/usr/bin/env python3
"""Measure deterministic routing quality and bounded latency on the golden fixture."""

from __future__ import annotations

import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from skill_router_plugin.planner import select_skills  # noqa: E402
from tests.routing_golden_support import (  # noqa: E402
    GOLDEN_CATALOG,
    _Ctx,
    projection,
    route_new,
    route_old,
    select_old,
)


def _percentile(values: list[int], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index] / 1_000_000


def _metrics(cases: list[dict], router) -> dict[str, float | int]:
    outputs = [(case, projection(router(case["task"]))) for case in cases]
    expected_empty = [item for item in outputs if not item[0]["expected"]]
    correct_empty = sum(not actual for _case, actual in expected_empty)
    primary_cases = [item for item in outputs if item[0]["expected"]]
    correct_primary = sum(
        next((item["name"] for item in actual if item["role"] == "primary"), None)
        == next(item["name"] for item in case["expected"] if item["role"] == "primary")
        for case, actual in primary_cases
    )
    expected_supporting = {(case["id"], item["name"]) for case, _actual in outputs for item in case["expected"] if item["role"] == "supporting"}
    actual_supporting = {(case["id"], item["name"]) for case, actual in outputs for item in actual if item["role"] == "supporting"}
    correct_supporting = actual_supporting & expected_supporting
    false_supporting = actual_supporting - expected_supporting
    false_positive_rate = (len(expected_empty) - correct_empty) / max(1, len(expected_empty))
    return {
        "no_skill_accuracy": correct_empty / max(1, len(expected_empty)),
        "false_positive_rate": false_positive_rate,
        "primary_skill_accuracy": correct_primary / max(1, len(primary_cases)),
        "supporting_skill_precision": len(correct_supporting) / max(1, len(actual_supporting)),
        "irrelevant_supporting_rate": len(false_supporting) / max(1, len(actual_supporting)),
        "no_skill_false_positives": len(expected_empty) - correct_empty,
        "wrong_primary": len(primary_cases) - correct_primary,
        "irrelevant_supporting": len(false_supporting),
    }


def _timing() -> dict[str, float | int]:
    catalog = []
    while len(catalog) < 76:
        for entry in GOLDEN_CATALOG:
            clone = dict(entry)
            clone["name"] = f"{entry['name']}-{len(catalog):02d}"
            catalog.append(clone)
            if len(catalog) == 76:
                break
    task = "Create a GitHub pull request and review its code diff."
    def calibrated() -> None:
        select_skills(_Ctx(), task, catalog, mode="deterministic", limit=4, catalog_chars=60_000)
    def legacy() -> None:
        select_old(task, catalog, limit=4)
    for _index in range(20):
        legacy(); calibrated()
    old_samples: list[int] = []
    new_samples: list[int] = []
    for index in range(300):
        first, second = (legacy, calibrated) if index % 2 == 0 else (calibrated, legacy)
        started = time.perf_counter_ns(); first(); first_elapsed = time.perf_counter_ns() - started
        started = time.perf_counter_ns(); second(); second_elapsed = time.perf_counter_ns() - started
        if index % 2 == 0: old_samples.append(first_elapsed); new_samples.append(second_elapsed)
        else: new_samples.append(first_elapsed); old_samples.append(second_elapsed)
    old_ms = statistics.median(old_samples) / 1_000_000
    new_ms = statistics.median(new_samples) / 1_000_000
    return {
        "catalog_size": len(catalog), "legacy_p50_ms": round(old_ms, 4), "calibrated_p50_ms": round(new_ms, 4),
        "calibrated_p95_ms": round(_percentile(new_samples, 0.95), 4), "additional_p50_ms": round(new_ms - old_ms, 4),
        "target_additional_p50_ms": 10.0,
    }


def main() -> int:
    document = json.loads((ROOT / "tests" / "fixtures" / "routing_golden.json").read_text(encoding="utf-8"))
    cases = document["cases"]
    report = {"cases": len(cases), "legacy": _metrics(cases, route_old), "calibrated": _metrics(cases, route_new), "timing": _timing()}
    print(json.dumps(report, indent=2, sort_keys=True))
    quality, timing = report["calibrated"], report["timing"]
    return 0 if (quality["no_skill_accuracy"] >= 0.95 and quality["false_positive_rate"] <= 0.05 and quality["primary_skill_accuracy"] >= 0.90 and quality["irrelevant_supporting_rate"] <= 0.10 and timing["additional_p50_ms"] < timing["target_additional_p50_ms"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
