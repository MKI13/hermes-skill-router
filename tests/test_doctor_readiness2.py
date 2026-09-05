from __future__ import annotations

from skill_router_plugin.doctor_readiness import render_readiness_doctor


def test_doctor_readiness2_counts_and_orders_actionable_skills():
    text = render_readiness_doctor({
        "entries": [
            {"name": "ready-one", "readiness_status": "ready"},
            {"name": "needs-setup", "readiness_status": "setup_required", "readiness_summary": "Setup required for 1 config item."},
            {"name": "missing-dep", "readiness_status": "dependency_missing", "readiness_summary": "Missing 1 dependency."},
            {"name": "broken-one", "readiness_status": "broken", "readiness_summary": "Invalid requirements declaration."},
            {"name": "unknown-one", "readiness_status": "unknown"},
        ]
    })

    assert "Indexed: 5" in text
    assert "broken=1" in text
    assert "dependency missing=1" in text
    assert "setup required=1" in text
    assert "unknown=1" in text
    assert "ready=1" in text
    assert text.index("broken-one") < text.index("missing-dep") < text.index("needs-setup") < text.index("unknown-one")
    assert "No repair was attempted." in text


def test_doctor_readiness2_is_bounded():
    entries = [
        {"name": f"skill-{index:02d}", "readiness_status": "unknown"}
        for index in range(12)
    ]
    text = render_readiness_doctor({"entries": entries}, detail_limit=3)

    assert text.count("\n- skill-") == 3
    assert "... 9 more" in text
    assert "inspect <skill>" in text


def test_doctor_readiness2_does_not_render_unrelated_cached_values():
    opaque_value = "-".join(("internal", "fixture", "value"))
    text = render_readiness_doctor({
        "entries": [{
            "name": "config-skill",
            "readiness_status": "setup_required",
            "setup_requirements": [{"type": "config", "name": "API_SETTING"}],
            "configured_value": opaque_value,
        }]
    })

    assert "API_SETTING" in text
    assert opaque_value not in text


def test_doctor_readiness2_all_ready_is_compact():
    text = render_readiness_doctor({
        "entries": [
            {"name": "alpha", "readiness_status": "ready"},
            {"name": "beta", "readiness_status": "ready"},
        ]
    })

    assert "Indexed: 2" in text
    assert "Actionable: none" in text
