"""The exit gate (plan 12 §6 D1).

`required_forms_complete` already covers "submitted and unexpired". These are
the content checks on top of it — a certification form completed with an ISO
27001 satisfies the form but not NHA.
"""

from __future__ import annotations

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from sandbox.experiences.models import SubmissionStatus

#: §3.2: STQC or CERT-In empanelled, and the artefact is a "Safe-to-Host"
#: certificate — the same thing under two names.
SAFE_TO_HOST_TYPES = frozenset({"wasa", "cert_in_audit"})


def exit_gate_blockers(context) -> tuple[str, ...]:
    """Everything standing between this application and submission."""
    blockers = []
    evidence = context.form_data("conformance_evidence")

    if not (
        evidence.get("functional_testing_agency")
        and evidence.get("functional_certificate_number")
    ):
        blockers.append(
            _("Record the functional testing agency and its certificate number."),
        )
    # Only the internal NHA demo gates submission; the HTC demo is a review step.
    if not evidence.get("demonstration_date"):
        blockers.append(_("Record the date of the internal ABDM demonstration."))
    if not has_safe_to_host_certificate(context):
        blockers.append(
            _("An unexpired WASA or CERT-In Safe-to-Host certificate is required."),
        )
    if not context.form_data("technical_readiness").get("production_callback_url"):
        blockers.append(
            _("Give the production callback URL before submitting the exit form."),
        )
    return tuple(blockers)


def has_safe_to_host_certificate(context) -> bool:
    today = timezone.localdate()
    return any(
        submission.is_current
        and submission.status == SubmissionStatus.COMPLETED
        and submission.data.get("certification_type") in SAFE_TO_HOST_TYPES
        and (submission.valid_until is None or submission.valid_until >= today)
        for submission in context.submission_history.get("security_certification", ())
    )
