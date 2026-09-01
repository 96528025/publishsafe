import math
from dataclasses import dataclass
from typing import Literal


# Policy thresholds are intentionally conservative heuristics, not calibrated
# identity probabilities. A tracker ID alone is not identity proof: both
# continuing IDs and recovered IDs must have strong, unambiguous appearance
# evidence before a person remains visible.
EXEMPTION_MAX_APPEARANCE_DISTANCE = 0.35
EXEMPTION_MIN_DETECTION_CONFIDENCE = 0.60
EXEMPTION_MIN_DISTANCE_MARGIN = 0.12


@dataclass(frozen=True)
class CreatorCandidate:
    track_id: int
    detection_confidence: float
    appearance_distance: float | None


@dataclass(frozen=True)
class CreatorDecision:
    exempt_track_id: int | None
    next_creator_track_id: int
    reason: Literal[
        "same_track_id",
        "unique_appearance_recovery",
        "conservative_fallback",
    ]
    fallback_detail: str | None = None


def select_creator_exemption(
    creator_track_id: int,
    candidates: list[CreatorCandidate],
) -> CreatorDecision:
    """Choose the only track that may remain visible on this frame.

    Every visible candidate must be comparable. A continuing tracker ID is
    retained only when its appearance remains strong and unambiguous; when the
    ID disappears, the best new candidate must meet those same constraints.
    Any uncertainty returns no exemption so the caller can protect every
    detected person.
    """
    if not candidates:
        return CreatorDecision(
            exempt_track_id=None,
            next_creator_track_id=creator_track_id,
            reason="conservative_fallback",
            fallback_detail="no_candidates",
        )

    if any(candidate.appearance_distance is None for candidate in candidates):
        return CreatorDecision(
            exempt_track_id=None,
            next_creator_track_id=creator_track_id,
            reason="conservative_fallback",
            fallback_detail="incomplete_appearance_evidence",
        )

    if any(
        not math.isfinite(float(candidate.appearance_distance))
        or float(candidate.appearance_distance) < 0.0
        or not math.isfinite(candidate.detection_confidence)
        or not 0.0 <= candidate.detection_confidence <= 1.0
        for candidate in candidates
    ):
        return CreatorDecision(
            exempt_track_id=None,
            next_creator_track_id=creator_track_id,
            reason="conservative_fallback",
            fallback_detail="invalid_candidate_evidence",
        )

    ranked = sorted(
        candidates,
        key=lambda candidate: float(candidate.appearance_distance),
    )
    continuing = next(
        (
            candidate
            for candidate in candidates
            if candidate.track_id == creator_track_id
        ),
        None,
    )
    if continuing is not None:
        continuing_distance = float(continuing.appearance_distance)
        if continuing.detection_confidence < EXEMPTION_MIN_DETECTION_CONFIDENCE:
            return CreatorDecision(
                exempt_track_id=None,
                next_creator_track_id=creator_track_id,
                reason="conservative_fallback",
                fallback_detail="low_detection_confidence",
            )
        if continuing_distance > EXEMPTION_MAX_APPEARANCE_DISTANCE:
            return CreatorDecision(
                exempt_track_id=None,
                next_creator_track_id=creator_track_id,
                reason="conservative_fallback",
                fallback_detail="weak_continuing_appearance",
            )
        other_distances = [
            float(candidate.appearance_distance)
            for candidate in candidates
            if candidate.track_id != creator_track_id
        ]
        if (
            other_distances
            and min(other_distances) - continuing_distance
            < EXEMPTION_MIN_DISTANCE_MARGIN
        ):
            return CreatorDecision(
                exempt_track_id=None,
                next_creator_track_id=creator_track_id,
                reason="conservative_fallback",
                fallback_detail="ambiguous_continuing_appearance",
            )
        return CreatorDecision(
            exempt_track_id=creator_track_id,
            next_creator_track_id=creator_track_id,
            reason="same_track_id",
        )

    best = ranked[0]
    best_distance = float(best.appearance_distance)
    if best.detection_confidence < EXEMPTION_MIN_DETECTION_CONFIDENCE:
        return CreatorDecision(
            exempt_track_id=None,
            next_creator_track_id=creator_track_id,
            reason="conservative_fallback",
            fallback_detail="low_detection_confidence",
        )
    if best_distance > EXEMPTION_MAX_APPEARANCE_DISTANCE:
        return CreatorDecision(
            exempt_track_id=None,
            next_creator_track_id=creator_track_id,
            reason="conservative_fallback",
            fallback_detail="weak_appearance_match",
        )
    if len(ranked) > 1:
        second_distance = float(ranked[1].appearance_distance)
        if second_distance - best_distance < EXEMPTION_MIN_DISTANCE_MARGIN:
            return CreatorDecision(
                exempt_track_id=None,
                next_creator_track_id=creator_track_id,
                reason="conservative_fallback",
                fallback_detail="ambiguous_appearance_match",
            )

    return CreatorDecision(
        exempt_track_id=best.track_id,
        next_creator_track_id=best.track_id,
        reason="unique_appearance_recovery",
    )
