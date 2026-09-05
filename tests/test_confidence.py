from skill_router_plugin.confidence import ConfidenceCandidate, choose_primary


def c(name, score, status, explicit=False):
    return ConfidenceCandidate(name=name, score=score, readiness_status=status, explicit=explicit)


def test_ready_fallback_wins_when_unknown_top_is_only_slightly_better():
    decision = choose_primary(
        [c("unknown", 42, "unknown"), c("ready", 39, "ready")],
        minimum_score=20,
        ready_fallback_margin=5,
    )

    assert decision.primary == "ready"
    assert decision.fallback_applied is True
    assert decision.confidence == "high"


def test_unknown_kept_when_ready_alternative_is_materially_weaker():
    decision = choose_primary(
        [c("unknown", 42, "unknown"), c("ready", 30, "ready")],
        minimum_score=20,
        ready_fallback_margin=5,
    )

    assert decision.primary == "unknown"
    assert decision.fallback_applied is False


def test_explicit_unknown_is_never_replaced_by_ready_fallback():
    decision = choose_primary(
        [c("unknown", 42, "unknown", explicit=True), c("ready", 41, "ready")],
        minimum_score=20,
        ready_fallback_margin=5,
    )

    assert decision.primary == "unknown"
    assert decision.fallback_applied is False
    assert "Explicit" in decision.reason


def test_irrelevant_ready_skill_is_not_promoted_by_readiness_alone():
    decision = choose_primary(
        [c("unknown", 19, "unknown"), c("ready", 18, "ready")],
        minimum_score=20,
    )

    assert decision.primary is None
    assert decision.confidence == "none"


def test_borderline_match_is_medium_confidence():
    decision = choose_primary(
        [c("ready", 24, "ready")],
        minimum_score=20,
        high_confidence_margin=10,
    )

    assert decision.primary == "ready"
    assert decision.confidence == "medium"


def test_strong_match_is_high_confidence():
    decision = choose_primary(
        [c("ready", 35, "ready")],
        minimum_score=20,
        high_confidence_margin=10,
    )

    assert decision.confidence == "high"
