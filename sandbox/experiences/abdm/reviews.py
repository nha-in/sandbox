"""Which reviewed evidence has gone stale since it was reviewed."""

from __future__ import annotations


def stale_reviews(context) -> tuple[str, ...]:
    """Reviewed forms whose revision has moved past the review, plus any never
    reviewed. Empty means the review still stands.

    Applicability is asked here too: a form that does not apply was never
    reviewed and must not read as stale for ever.
    """
    from sandbox.experiences.abdm.definition import ReviewEvidence  # noqa: PLC0415

    verified = context.application.outcome.get("verified_revisions", {})
    return tuple(
        key
        for key in ReviewEvidence.applicable_reviewed_forms(context)
        if key in context.submissions
        and verified.get(key) != context.submissions[key].revision
    )
