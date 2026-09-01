"""Pure creator-exemption decisions must fail closed under uncertainty."""

import math

from app.privacy import CreatorCandidate, select_creator_exemption


def candidate(track_id, confidence=0.9, distance=0.1):
    return CreatorCandidate(
        track_id=track_id,
        detection_confidence=confidence,
        appearance_distance=distance,
    )


def test_no_candidates_produces_no_exemption():
    decision = select_creator_exemption(7, [])

    assert decision.exempt_track_id is None
    assert decision.next_creator_track_id == 7
    assert decision.reason == "conservative_fallback"
    assert decision.fallback_detail == "no_candidates"


def test_single_confident_same_track_id_is_exempted():
    decision = select_creator_exemption(
        7,
        [candidate(7, confidence=0.9, distance=0.1)],
    )

    assert decision.exempt_track_id == 7
    assert decision.next_creator_track_id == 7
    assert decision.reason == "same_track_id"


def test_same_track_id_with_poor_appearance_is_not_exempted():
    decision = select_creator_exemption(
        7,
        [candidate(7, confidence=0.9, distance=0.36)],
    )

    assert decision.exempt_track_id is None
    assert decision.reason == "conservative_fallback"
    assert decision.fallback_detail == "weak_continuing_appearance"


def test_same_track_id_with_an_appearance_tie_is_not_exempted():
    decision = select_creator_exemption(
        7,
        [candidate(7, distance=0.10), candidate(8, distance=0.10)],
    )

    assert decision.exempt_track_id is None
    assert decision.reason == "conservative_fallback"
    assert decision.fallback_detail == "ambiguous_continuing_appearance"


def test_unique_high_confidence_appearance_match_recovers_a_new_id():
    decision = select_creator_exemption(
        7,
        [candidate(11, distance=0.12), candidate(12, distance=0.55)],
    )

    assert decision.exempt_track_id == 11
    assert decision.next_creator_track_id == 11
    assert decision.reason == "unique_appearance_recovery"


def test_ambiguous_appearance_matches_exempt_nobody():
    decision = select_creator_exemption(
        7,
        [candidate(11, distance=0.12), candidate(12, distance=0.19)],
    )

    assert decision.exempt_track_id is None
    assert decision.next_creator_track_id == 7
    assert decision.reason == "conservative_fallback"
    assert decision.fallback_detail == "ambiguous_appearance_match"


def test_incomplete_appearance_evidence_exempts_nobody():
    decision = select_creator_exemption(
        7,
        [candidate(11, distance=0.12), candidate(12, distance=None)],
    )

    assert decision.exempt_track_id is None
    assert decision.fallback_detail == "incomplete_appearance_evidence"


def test_non_finite_candidate_evidence_exempts_nobody():
    decision = select_creator_exemption(7, [candidate(7, distance=math.nan)])

    assert decision.exempt_track_id is None
    assert decision.fallback_detail == "invalid_candidate_evidence"


def test_low_detection_confidence_exempts_nobody():
    decision = select_creator_exemption(7, [candidate(11, confidence=0.59)])

    assert decision.exempt_track_id is None
    assert decision.fallback_detail == "low_detection_confidence"


def test_weak_appearance_match_exempts_nobody():
    decision = select_creator_exemption(7, [candidate(11, distance=0.36)])

    assert decision.exempt_track_id is None
    assert decision.fallback_detail == "weak_appearance_match"
