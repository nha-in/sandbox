"""Which reviewed evidence has gone stale since it was reviewed."""

from __future__ import annotations


def stale_reviews(application, submissions) -> tuple[str, ...]:
    """Reviewed forms whose current revision is newer than the review, plus any
    never reviewed at all. Empty means the review still stands."""
    from sandbox.experiences.abdm.definition import ReviewEvidence  # noqa: PLC0415

    verified = application.outcome.get("verified_revisions", {})
    return tuple(
        key
        for key in ReviewEvidence.reviewed_forms
        if key in submissions and verified.get(key) != submissions[key].revision
    )
