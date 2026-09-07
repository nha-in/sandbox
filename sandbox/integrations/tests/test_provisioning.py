"""What an approval causes: the chain, the ledger, the attempt record, the mail.

The chain's own bookkeeping — idempotency, secret handling, backoff — is the
older half of this file and is unchanged in substance. The newer half is the
seam plan 12 §7 rebuilt: approval reaches the chain as an `effects` entry, the
state it used to write onto the application is a `ProvisioningRun` row now, and
a retry is a registry action rather than a bare service call.
"""

from __future__ import annotations

import pytest
from celery.exceptions import Retry
from django.test import override_settings
from django.utils import timezone

from sandbox.experiences.services import perform_application_action
from sandbox.integrations import fakes
from sandbox.integrations.credentials import take_initial_secret
from sandbox.integrations.fakes import always_fail
from sandbox.integrations.fakes import fail_next
from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedResourceState
from sandbox.integrations.models import ProvisionedSystem
from sandbox.integrations.ports import ExternalSystem
from sandbox.integrations.secret_ref import discard_secret
from sandbox.integrations.secret_ref import resolve_secret
from sandbox.integrations.tasks import _external_name
from sandbox.integrations.tasks import complete_provisioning
from sandbox.integrations.tasks import enqueue_chain
from sandbox.integrations.tasks import provision_keycloak
from sandbox.integrations.tasks import provision_wso2
from sandbox.notifications.models import Message
from sandbox.notifications.models import TemplateKey
from sandbox.organisations.models import ProvisioningRun
from sandbox.utils.correlation import set_correlation_id

pytestmark = pytest.mark.django_db

ALL_SYSTEMS = set(ProvisionedSystem.values)
BACKOFF_SEQUENCE = [120, 240, 480, 900]


def _systems(application) -> set[str]:
    return set(
        ProvisionedResource.objects.filter(
            application=application,
            state=ProvisionedResourceState.ACTIVE,
        ).values_list("system", flat=True),
    )


def _refs(application) -> dict[int, str]:
    return {row.pk: row.external_ref for row in application.provisioned_resources.all()}


def _reviewed(application, reviewer):
    """§4.7: approval waits on the evidence review."""
    perform_application_action(
        application=application,
        action_key="review_evidence",
        user=reviewer,
        cleaned_data={
            "hard_copy_received_on": timezone.localdate(),
            "verified_milestones": [],
        },
    )


def _run(application) -> ProvisioningRun:
    return application.provisioning_runs.order_by("-started_at").first()


# ── The seam: approval reaches the chain ─────────────────────────────────────


def test_approval_provisions_all_three_systems(approve):
    application = approve()

    assert _systems(application) == ALL_SYSTEMS


def test_approval_opens_an_attempt_record_and_closes_it_ready(approve):
    """Where "is this provisioned?" is answered now the application status
    cannot: `approved` says what NHA decided, not what the adapters did."""
    application = approve()

    run = _run(application)
    assert run.status == ProvisioningRun.Status.READY
    assert run.finished_at is not None
    assert not run.error


def test_approval_sends_the_decision_mail_and_completion_sends_the_credentials_link(
    approve,
):
    """Two mails, from two places. The decision is an `effects` entry on the
    action; the credentials link fires on a completion nobody performed."""
    application = approve()

    messages = Message.objects.filter(application=application)

    assert {message.template_key for message in messages} == {
        TemplateKey.PRODUCTION_APPROVED,
        TemplateKey.SANDBOX_APPROVED,
    }
    # The applicant, never the reviewer who acted.
    assert {message.recipient for message in messages} == {
        application.created_by.email,
    }


def test_the_credentials_mail_carries_a_link_and_never_the_secret(approve):
    """Legacy mailed the client secret itself. The panel link is the fix."""
    application = approve()

    message = Message.objects.get(
        application=application,
        template_key=TemplateKey.SANDBOX_APPROVED,
    )
    assert message.params["panel_url"].endswith(application.reference + "/")
    secret = resolve_secret(
        ProvisionedResource.objects.get(
            application=application,
            system=ProvisionedSystem.KEYCLOAK,
        ).secret_ref,
        ExternalSystem.KEYCLOAK,
    )
    assert secret not in str(message.params)


def test_nothing_is_provisioned_until_the_approval_commits(
    under_review,
    reviewer,
    django_capture_on_commit_callbacks,
):
    """The reason the chain is an effect: an adapter must never create a client
    for a decision that then rolls back."""
    _reviewed(under_review, reviewer)
    with django_capture_on_commit_callbacks(execute=False):
        perform_application_action(
            application=under_review,
            action_key="approve",
            user=reviewer,
            cleaned_data={
                "production_client_id": "PROD-CLIENT-1001",
                "approved_milestones": ["m1"],
                "certificate_reference": "CERT-1",
                "effective_date": None,
            },
        )
        assert not ProvisionedResource.objects.filter(
            application=under_review,
        ).exists()


# ── The ledger ───────────────────────────────────────────────────────────────


def test_the_keycloak_row_carries_both_references(approve):
    """`external_ref` is what teardown disables; `public_ref` is what C7 shows."""
    application = approve()

    row = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
    )
    assert row.external_ref
    assert row.public_ref.startswith("SBX_")
    assert row.external_ref != row.public_ref


def test_the_bridge_is_named_after_the_client(approve):
    application = approve()

    rows = {row.system: row for row in application.provisioned_resources.all()}
    assert (
        rows[ProvisionedSystem.HIECM].external_ref
        == rows[ProvisionedSystem.KEYCLOAK].public_ref
    )


def test_re_running_the_chain_creates_nothing_new(
    approve,
    django_capture_on_commit_callbacks,
):
    """The kill-and-retry property, expressed as "run it twice"."""
    application = approve()
    before = _refs(application)

    with django_capture_on_commit_callbacks(execute=True):
        enqueue_chain(application)

    assert _refs(application) == before
    assert _run(application).status == ProvisioningRun.Status.READY


# ── Failure ──────────────────────────────────────────────────────────────────


@override_settings(PROVISIONING_MAX_ATTEMPTS=1)
def test_a_failing_step_closes_the_attempt_with_the_reason(approve):
    always_fail(ExternalSystem.KEYCLOAK, code="REALM_DOWN", retryable=True)

    application = approve()

    run = _run(application)
    assert run.status == ProvisioningRun.Status.FAILED
    assert "REALM_DOWN" in run.error
    assert "KEYCLOAK" in run.error


def test_a_failed_step_stops_the_rest_of_the_chain(approve):
    fail_next(ExternalSystem.KEYCLOAK, "create_client", retryable=False)

    application = approve()

    assert _systems(application) == set()
    assert _run(application).status == ProvisioningRun.Status.FAILED


def test_a_failed_chain_sends_no_credentials_mail(approve):
    fail_next(ExternalSystem.KEYCLOAK, "create_client", retryable=False)

    application = approve()

    assert not Message.objects.filter(
        application=application,
        template_key=TemplateKey.SANDBOX_APPROVED,
    ).exists()


def test_a_missing_api_name_list_fails_without_retrying(approve):
    """Configuration is not a transient fault, so it must not burn five attempts."""
    with override_settings(WSO2_API_NAMES={"abdm_production_access": ()}):
        application = approve()

    # And the bridge is not built: a closed attempt stops the links after it.
    assert _systems(application) == {ProvisionedSystem.KEYCLOAK}
    assert "CONFIG_ERROR" in _run(application).error


def test_a_retryable_failure_retries_instead_of_closing_the_attempt(under_review):
    """A transient fault must leave the attempt open, or the retry lands in a
    run that already reads FAILED and the console offers a second retry."""
    ProvisioningRun.objects.create(application=under_review)
    always_fail(ExternalSystem.KEYCLOAK, code="REALM_DOWN", retryable=True)

    with pytest.raises(Retry):
        provision_keycloak.delay(under_review.pk)

    assert _run(under_review).status == ProvisioningRun.Status.RUNNING
    assert not ProvisionedResource.objects.filter(application=under_review).exists()


def test_backoff_doubles_and_is_capped():
    from sandbox.integrations.tasks import _backoff  # noqa: PLC0415

    with override_settings(
        PROVISIONING_RETRY_BACKOFF_SECONDS=120,
        PROVISIONING_RETRY_BACKOFF_MAX_SECONDS=900,
    ):
        assert [_backoff(n) for n in range(4)] == BACKOFF_SEQUENCE


def test_completion_refuses_an_incomplete_ledger(under_review):
    """READY is a claim about three systems, not about the chain running.

    The chain reached completion with nothing to blame — no step failed, and
    the ledger is short anyway. Defensive, and the only path on which
    completion is the one that closes the attempt.
    """
    ProvisioningRun.objects.create(application=under_review)

    complete_provisioning.delay(under_review.pk)

    run = _run(under_review)
    assert run.status == ProvisioningRun.Status.FAILED
    assert "incomplete ledger" in run.error
    assert not Message.objects.filter(
        application=under_review,
        template_key=TemplateKey.SANDBOX_APPROVED,
    ).exists()


def test_a_failed_chain_records_the_failure_once(approve):
    """Completion sees the same short ledger the failed step already explained.

    Recording it again would put two `provisioning.failed` events on the
    timeline for one failure, the second naming no cause.
    """
    fail_next(ExternalSystem.WSO2, "create_application", retryable=False)
    application = approve()

    events = application.events.filter(action_key="provisioning.failed")

    assert events.count() == 1
    assert events.get().payload["system"] == ProvisionedSystem.WSO2
    assert _run(application).error.startswith("WSO2/")


# ── The retry action ─────────────────────────────────────────────────────────


def test_a_retry_provisions_only_the_missing_system(
    approve,
    reviewer,
    django_capture_on_commit_callbacks,
):
    fail_next(ExternalSystem.HIECM, "create_bridge", retryable=False)
    application = approve()

    assert _systems(application) == {
        ProvisionedSystem.KEYCLOAK,
        ProvisionedSystem.WSO2,
    }
    keycloak_before = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
    ).external_ref

    with django_capture_on_commit_callbacks(execute=True):
        perform_application_action(
            application=application,
            action_key="retry_provisioning",
            user=reviewer,
        )

    assert _systems(application) == ALL_SYSTEMS
    assert (
        ProvisionedResource.objects.get(
            application=application,
            system=ProvisionedSystem.KEYCLOAK,
        ).external_ref
        == keycloak_before
    )


def test_a_retry_opens_a_second_attempt_and_names_who_asked(
    approve,
    reviewer,
    django_capture_on_commit_callbacks,
):
    """What the retry lost when `sandbox/workflow/` went, and gets back here."""
    fail_next(ExternalSystem.HIECM, "create_bridge", retryable=False)
    application = approve()

    with django_capture_on_commit_callbacks(execute=True):
        perform_application_action(
            application=application,
            action_key="retry_provisioning",
            user=reviewer,
        )

    runs = list(application.provisioning_runs.order_by("started_at"))
    assert [run.status for run in runs] == [
        ProvisioningRun.Status.FAILED,
        ProvisioningRun.Status.READY,
    ]
    assert runs[1].started_by == reviewer
    assert application.events.filter(
        action_key="retry_provisioning",
        actor=reviewer,
    ).exists()


def test_a_retry_is_offered_only_after_a_failure(approve, reviewer):
    from sandbox.experiences.registry import registry  # noqa: PLC0415
    from sandbox.experiences.services import application_context  # noqa: PLC0415

    application = approve()
    context = application_context(application, reviewer)
    action = registry.get(application.application_type).get_action(
        "retry_provisioning",
    )

    available, reason = action.availability(context)

    assert available is False
    assert "did not fail" in str(reason)


def test_a_reviewer_without_the_retry_permission_is_refused(approve, owner):
    from django.core.exceptions import PermissionDenied  # noqa: PLC0415

    fail_next(ExternalSystem.HIECM, "create_bridge", retryable=False)
    application = approve()

    with pytest.raises(PermissionDenied):
        perform_application_action(
            application=application,
            action_key="retry_provisioning",
            user=owner,
        )


# ── Secrets ──────────────────────────────────────────────────────────────────


def test_no_secret_is_persisted_anywhere(approve):
    application = approve()

    row = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
    )
    secret = resolve_secret(row.secret_ref, ExternalSystem.KEYCLOAK)
    assert secret
    # The ref is a cache key; the value must appear in no column of any row.
    stored = " ".join(
        f"{r.external_ref}{r.public_ref}{r.secret_ref}"
        for r in ProvisionedResource.objects.all()
    )
    assert secret not in stored


def test_the_initial_secret_can_be_read_exactly_once(approve):
    application = approve()

    assert take_initial_secret(application)
    assert take_initial_secret(application) is None


def test_an_expired_parked_secret_is_re_minted_rather_than_dead_ending(under_review):
    """`SECRET_REF_TTL_SECONDS` is shorter than this chain's own retry budget.

    Without rotation, a WSO2 outage outlasting the TTL reaches a step that can
    never succeed: Keycloak is already ACTIVE so it is skipped, and nothing else
    mints a replacement secret.
    """
    provision_keycloak.delay(under_review.pk)

    row = ProvisionedResource.objects.get(
        application=under_review,
        system=ProvisionedSystem.KEYCLOAK,
    )
    expired_ref = row.secret_ref
    stale_secret = resolve_secret(expired_ref, ExternalSystem.KEYCLOAK)
    discard_secret(expired_ref)

    provision_wso2.delay(under_review.pk)

    row.refresh_from_db()
    assert row.secret_ref != expired_ref
    # A new ref alone would still pass if we had re-parked the same value, which
    # would leave WSO2 holding a secret Keycloak no longer honours.
    assert resolve_secret(row.secret_ref, ExternalSystem.KEYCLOAK) != stale_secret
    assert ProvisionedSystem.WSO2 in _systems(under_review)


# ── Correlation ──────────────────────────────────────────────────────────────


def test_the_chain_carries_the_id_the_approval_was_made_under(
    under_review,
    reviewer,
    django_capture_on_commit_callbacks,
):
    """One id ties the decision to the credentials it caused."""
    set_correlation_id("cccccccccccccccccccccccccccccccc")

    _reviewed(under_review, reviewer)
    with django_capture_on_commit_callbacks(execute=True):
        perform_application_action(
            application=under_review,
            action_key="approve",
            user=reviewer,
            cleaned_data={
                "production_client_id": "PROD-CLIENT-1001",
                "approved_milestones": ["m1"],
                "certificate_reference": "CERT-1",
                "effective_date": None,
            },
        )

    assert _run(under_review).correlation_id == "cccccccccccccccccccccccccccccccc"


# ── The name that goes out ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("stored", "sent"),
    [
        ("Sunrise Health (P) Ltd.", "Sunrise Health P Ltd"),
        ("M/s Ādi & Co.", "M s di Co"),
        ("  Sunrise  ", "Sunrise"),
        ("Sunrise-Health_Systems", "Sunrise Health Systems"),
    ],
)
def test_punctuation_is_stripped_before_the_name_reaches_keycloak(
    under_review,
    reviewer,
    django_capture_on_commit_callbacks,
    stored,
    sent,
):
    """Legacy stripped every non-alphanumeric before sending, so nothing NHA
    runs has ever been handed a name with punctuation in it."""
    under_review.organisation.name = stored
    under_review.organisation.legal_name = ""
    under_review.organisation.save(update_fields=["name", "legal_name"])

    _reviewed(under_review, reviewer)
    with django_capture_on_commit_callbacks(execute=True):
        perform_application_action(
            application=under_review,
            action_key="approve",
            user=reviewer,
            cleaned_data={
                "production_client_id": "PROD-CLIENT-1001",
                "approved_milestones": ["m1"],
                "certificate_reference": "CERT-1",
                "effective_date": None,
            },
        )

    row = ProvisionedResource.objects.get(
        application=under_review,
        system=ProvisionedSystem.KEYCLOAK,
    )
    assert fakes.FakeIdpAdmin().get_client(row.external_ref)["display_name"] == sent


def test_a_name_of_pure_punctuation_falls_back_to_the_reference(under_review):
    """An empty display name identifies nobody, so something has to give."""
    under_review.organisation.name = "!!!"
    under_review.organisation.legal_name = ""
    under_review.organisation.save(update_fields=["name", "legal_name"])

    assert _external_name(under_review) == under_review.reference.replace("-", " ")
