from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.utils.datastructures import MultiValueDict

from sandbox.experiences import permission_keys
from sandbox.experiences.models import ApplicationFormSubmission
from sandbox.experiences.models import QueryStatus
from sandbox.experiences.models import ReviewRole
from sandbox.experiences.models import ReviewRoleAssignment
from sandbox.experiences.permissions import get_effective_access
from sandbox.experiences.registry import registry
from sandbox.experiences.services import application_context
from sandbox.experiences.services import assignable_roles
from sandbox.experiences.services import create_application
from sandbox.experiences.services import grant_application_access
from sandbox.experiences.services import perform_application_action
from sandbox.experiences.services import post_query_reply
from sandbox.experiences.services import recalculate_progress
from sandbox.experiences.services import resolve_query
from sandbox.experiences.services import save_form_submission
from sandbox.experiences.tests.factories import gate_data
from sandbox.experiences.views import _submission_rows
from sandbox.organisations.models import Membership
from sandbox.organisations.models import Role
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

APPLICATION_TYPE = "abdm_production_access"
FORM_COUNT = 11
#: `production_details` is not required — the review team fills it after approval.
REQUIRED_FORM_COUNT = 10
BASE_REQUIRED_FORM_COUNT = 9
SCOPED_COMPLETED_FORM_COUNT = 3
SCOPED_PROGRESS_PERCENT = 30
BASE_PROGRESS_PERCENT = 33
MULTI_FILE_COUNT = 2
RENEWED_SUBMISSION_NUMBER = 2
EDITED_REVISION_NUMBER = 2
EDITED_VERSION_COUNT = 2
RENEWAL_HISTORY_VERSION_COUNT = 3
TOTAL_MULTI_FILE_COUNT = 4
MAX_CERTIFICATE_FILES = 5
APPENDED_CERTIFICATE_FILE_COUNT = 3
RETAINED_SUPPORTING_FILE_COUNT = 1


@pytest.fixture
def actors():
    organisation = OrganisationFactory(onboarded=True)
    owner = UserFactory(email="owner@example.in")
    contributor = UserFactory(email="contributor@example.in")
    reviewer = UserFactory(
        email="reviewer@nha.gov.in",
        is_staff=True,
    )
    Membership.objects.create(
        organisation=organisation,
        user=owner,
        role=Role.OWNER,
    )
    Membership.objects.create(
        organisation=organisation,
        user=contributor,
        role=Role.DEVELOPER,
    )
    return organisation, owner, contributor, reviewer


@pytest.fixture
def application(actors):
    organisation, owner, _contributor, reviewer = actors
    application = create_application(
        application_type=APPLICATION_TYPE,
        organisation=organisation,
        user=owner,
    )
    ReviewRoleAssignment.objects.create(
        user=reviewer,
        role=ReviewRole.objects.get(key="decision_maker"),
        granted_by=reviewer,
    )
    return application


def complete_all_forms(application, owner) -> None:
    """Every form complete, and enough content to clear §6 D1's exit gate."""
    definition = registry.get(APPLICATION_TYPE)
    for form_definition in definition.forms:
        ApplicationFormSubmission.objects.create(
            application=application,
            form_key=form_definition.key,
            data=gate_data().get(form_definition.key, {}),
            submitted_by=owner,
        )


def test_definition_exposes_static_forms_roles_permissions_and_actions():
    definition = registry.get(APPLICATION_TYPE)

    assert len(definition.forms) == FORM_COUNT
    assert {role.key for role in definition.roles} >= {
        "applicant_owner",
        "applicant_viewer",
    }
    # The three platform roles left the registry in plan 12 §5 — they are
    # ReviewRole rows now, so a definition declares applicant roles only.
    assert not any(role.audience == "platform" for role in definition.roles)
    assert {permission.key for permission in definition.permissions} >= {
        permission_keys.EDIT_FORMS,
        permission_keys.OPEN_QUERY,
        permission_keys.RAISE_QUERY,
        permission_keys.APPROVE_APPLICATION,
    }
    assert {action.key for action in definition.actions} == {
        "submit",
        "withdraw",
        "ask_review_team",
        "start_review",
        "raise_query",
        "review_evidence",
        "approve",
        "reject",
        "retry_provisioning",
        "retry_deprovisioning",
    }
    # Plan 12 §6 E2 closed the gap this used to pin: the permission key and
    # `withdrawn` status both existed with no action reaching either.
    assert permission_keys.WITHDRAW_APPLICATION in {
        permission.key for permission in definition.permissions
    }


def test_new_application_grants_owner_permissions_and_gates_forms(application, actors):
    _organisation, owner, _contributor, _reviewer = actors
    context = application_context(application, owner)
    states = registry.get(APPLICATION_TYPE).form_states(context)

    by_key = {state.definition.key: state for state in states}

    assert get_effective_access(application, owner).role.key == "applicant_owner"
    assert context.has_permission(permission_keys.SUBMIT_APPLICATION)
    assert by_key["organisation_profile"].can_submit is True
    # Gated behind dependencies, not permissions.
    assert by_key["product_use_case"].visible is False
    assert by_key["declaration"].visible is False
    # In scope for the application, but never listed to the applicant (§4.8).
    assert by_key["production_details"].visible is True
    assert by_key["production_details"].listed is False


def test_contributor_cannot_receive_platform_permissions(application, actors):
    _organisation, owner, contributor, _reviewer = actors

    with pytest.raises(PermissionDenied):
        grant_application_access(
            application=application,
            actor=owner,
            target_user=contributor,
            role_key="applicant_contributor",
            direct_permissions=[permission_keys.APPROVE_APPLICATION],
        )


def test_delegated_inviter_cannot_grant_more_than_they_have(application, actors):
    organisation, owner, contributor, _reviewer = actors
    invitee = UserFactory(email="invitee@example.in")
    Membership.objects.create(
        organisation=organisation,
        user=invitee,
        role=Role.DEVELOPER,
    )
    grant_application_access(
        application=application,
        actor=owner,
        target_user=contributor,
        role_key="applicant_contributor",
        direct_permissions=[permission_keys.MANAGE_APPLICANT_ACCESS],
    )

    role_keys = {role.key for role in assignable_roles(application, contributor)}
    assert role_keys == {"applicant_contributor", "applicant_viewer"}

    grant = grant_application_access(
        application=application,
        actor=contributor,
        target_user=invitee,
        role_key="applicant_viewer",
    )
    assert grant.role_key == "applicant_viewer"

    with pytest.raises(PermissionDenied):
        grant_application_access(
            application=application,
            actor=contributor,
            target_user=invitee,
            role_key="applicant_submitter",
        )
    with pytest.raises(PermissionDenied):
        grant_application_access(
            application=application,
            actor=contributor,
            target_user=invitee,
            role_key="applicant_viewer",
            direct_permissions=[permission_keys.SUBMIT_APPLICATION],
        )


def test_application_owner_role_cannot_be_replaced(application, actors):
    _organisation, owner, _contributor, reviewer = actors

    with pytest.raises(PermissionDenied):
        grant_application_access(
            application=application,
            actor=reviewer,
            target_user=owner,
            role_key="review_observer",
        )


def test_application_actions_use_effective_permissions(application, actors):
    _organisation, owner, _contributor, reviewer = actors
    complete_all_forms(application, owner)
    owner_grant = application.access_grants.get(user=owner)
    owner_grant.direct_permissions = [permission_keys.APPROVE_APPLICATION]
    owner_grant.save(update_fields=["direct_permissions", "updated_at"])

    owner_states = registry.get(APPLICATION_TYPE).action_states(
        application_context(application, owner),
    )
    owner_actions = {item.definition.key: item.available for item in owner_states}
    assert owner_actions["submit"] is True
    assert owner_actions["ask_review_team"] is True
    assert owner_actions["approve"] is False
    assert not get_effective_access(application, owner).allows(
        permission_keys.APPROVE_APPLICATION,
    )

    perform_application_action(
        application=application,
        action_key="submit",
        user=owner,
    )
    application.refresh_from_db()
    reviewer_states = registry.get(APPLICATION_TYPE).action_states(
        application_context(application, reviewer),
    )
    reviewer_actions = {item.definition.key: item.available for item in reviewer_states}
    assert reviewer_actions["start_review"] is True
    assert reviewer_actions["ask_review_team"] is False
    # Withdrawal is the applicant's alone: plan 12 §6 E2 gave it to the owner,
    # so it is offered to a reviewer and refused, not absent.
    assert reviewer_actions["withdraw"] is False


def test_progress_uses_forms_applicable_to_the_current_scope(application, actors):
    _organisation, owner, _contributor, _reviewer = actors
    for form_key, data in (
        ("organisation_profile", {}),
        ("product_use_case", {}),
        ("integration_scope", {"abdm_roles": ["hip", "health_locker"]}),
    ):
        ApplicationFormSubmission.objects.create(
            application=application,
            form_key=form_key,
            data=data,
            submitted_by=owner,
        )

    recalculate_progress(application, user=owner)
    application.refresh_from_db()
    context = application_context(application, owner)
    health_locker_state = next(
        state
        for state in registry.get(APPLICATION_TYPE).form_states(context)
        if state.definition.key == "health_locker_operations"
    )

    assert application.metadata["completed_forms"] == SCOPED_COMPLETED_FORM_COUNT
    assert application.metadata["required_forms"] == REQUIRED_FORM_COUNT
    assert application.progress_percent == SCOPED_PROGRESS_PERCENT
    assert health_locker_state.applicable is True
    assert health_locker_state.visible is True

    integration = application.submissions.get(form_key="integration_scope")
    integration.data = {"abdm_roles": ["hip"]}
    integration.save(update_fields=["data", "updated_at"])
    recalculate_progress(application, user=owner)
    application.refresh_from_db()
    context = application_context(application, owner)
    health_locker_state = next(
        state
        for state in registry.get(APPLICATION_TYPE).form_states(context)
        if state.definition.key == "health_locker_operations"
    )

    assert application.metadata["required_forms"] == BASE_REQUIRED_FORM_COUNT
    assert application.progress_percent == BASE_PROGRESS_PERCENT
    assert health_locker_state.applicable is False
    assert health_locker_state.visible is False


def test_completed_form_update_policy_is_declared_per_form(application, actors):
    _organisation, owner, _contributor, _reviewer = actors
    complete_all_forms(application, owner)
    context = application_context(application, owner)
    definition = registry.get(APPLICATION_TYPE)

    profile_available, _reason = definition.get_form(
        "organisation_profile",
    ).availability(context)
    declaration_available, declaration_reason = definition.get_form(
        "declaration",
    ).availability(context)

    assert profile_available is True
    assert declaration_available is False
    assert "locked" in str(declaration_reason).lower()


def test_editable_form_saves_immutable_revisions(application, actors):
    organisation, owner, _contributor, _reviewer = actors
    form_definition = registry.get(APPLICATION_TYPE).get_form(
        "organisation_profile",
    )
    first_data = {
        "legal_entity_name": "Original Health Private Limited",
        "organisation_type": "company",
        "registration_number": "U12345KA2024PTC123456",
        "registered_address": "1 Original Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "pincode": "560001",
        "website": "https://original.example.in",
        "authorised_contact_name": owner.display_name,
        "authorised_contact_email": owner.email,
        "authorised_contact_phone": "+91 90000 00000",
    }
    first_form = form_definition.build_form(
        context=application_context(application, owner),
        data=first_data,
    )
    assert first_form.is_valid(), first_form.errors
    first = save_form_submission(
        application=application,
        form_key=form_definition.key,
        form=first_form,
        user=owner,
    )
    first.field_schema[0]["label"] = "Historic registered name"
    first.save(update_fields=["field_schema"])

    updated_data = {**first_data, "legal_entity_name": organisation.display_name}
    updated_form = form_definition.build_form(
        context=application_context(application, owner),
        data=updated_data,
        submission_mode="edit",
    )
    assert updated_form.is_valid(), updated_form.errors
    updated = save_form_submission(
        application=application,
        form_key=form_definition.key,
        form=updated_form,
        user=owner,
        submission_mode="edit",
    )
    first.refresh_from_db()

    assert first.is_current is False
    assert first.data["legal_entity_name"] == "Original Health Private Limited"
    assert updated.is_current is True
    assert updated.submission_number == first.submission_number
    assert updated.revision == EDITED_REVISION_NUMBER
    assert (
        application.submissions.filter(form_key=form_definition.key).count()
        == EDITED_VERSION_COUNT
    )
    historical_rows = _submission_rows(form_definition, first)
    assert historical_rows[0]["label"] == "Historic registered name"
    assert historical_rows[0]["value"] == "Original Health Private Limited"


def test_repeatable_form_retains_history_and_multiple_file_groups(  # noqa: PLR0915
    application,
    actors,
    settings,
    tmp_path,
):
    settings.MEDIA_ROOT = tmp_path
    _organisation, owner, _contributor, _reviewer = actors
    complete_all_forms(application, owner)
    application.status = "approved"
    application.save(update_fields=["status", "updated_at"])
    current = application.submissions.get(
        form_key="security_certification",
        is_current=True,
    )
    current.data = {
        "certificate_number": "CERT-OLD",
        "expires_on": (timezone.localdate() + timedelta(days=10)).isoformat(),
    }
    current.valid_until = timezone.localdate() + timedelta(days=10)
    current.save(update_fields=["data", "valid_until", "updated_at"])

    definition = registry.get(APPLICATION_TYPE)
    context = application_context(application, owner)
    state = next(
        item
        for item in definition.form_states(context)
        if item.definition.key == "security_certification"
    )
    assert state.renewal_due is True
    assert state.action_label == "Renew"
    assert state.can_submit is True

    form_definition = definition.get_form("security_certification")
    renewal_form = form_definition.build_form(context=context)
    edit_current_form = form_definition.build_form(
        context=context,
        submission_mode="edit",
    )
    assert renewal_form.initial == {}
    assert renewal_form.existing_files == {}
    assert edit_current_form.initial["certificate_number"] == "CERT-OLD"
    renewal_data = {
        "certification_type": "iso_27001",
        "certification_name": "ISO 27001 certification",
        "issuing_body": "Example Assurance Body",
        "certificate_number": "ISO-NEW-2026",
        "issued_on": (timezone.localdate() - timedelta(days=5)).isoformat(),
        "expires_on": (timezone.localdate() + timedelta(days=365)).isoformat(),
        "scope_summary": "ABDM production services and supporting cloud controls.",
    }
    form = form_definition.build_form(
        context=context,
        data=renewal_data,
        files=MultiValueDict(
            {
                "certificate_documents": [
                    SimpleUploadedFile(
                        "certificate.pdf",
                        b"certificate",
                        content_type="application/pdf",
                    ),
                    SimpleUploadedFile(
                        "scope-annexure.pdf",
                        b"annexure",
                        content_type="application/pdf",
                    ),
                ],
                "supporting_documents": [
                    SimpleUploadedFile(
                        "control-map.pdf",
                        b"controls",
                        content_type="application/pdf",
                    ),
                    SimpleUploadedFile(
                        "audit-cover.png",
                        b"image",
                        content_type="image/png",
                    ),
                ],
            },
        ),
    )
    assert form.is_valid(), form.errors

    renewed = save_form_submission(
        application=application,
        form_key="security_certification",
        form=form,
        user=owner,
        submission_mode="renew",
    )
    current.refresh_from_db()
    application.refresh_from_db()

    assert application.status == "approved"
    assert current.is_current is False
    assert renewed.is_current is True
    assert renewed.submission_number == RENEWED_SUBMISSION_NUMBER
    assert renewed.valid_until == timezone.localdate() + timedelta(days=365)
    assert len(renewed.data["certificate_documents"]) == MULTI_FILE_COUNT
    assert len(renewed.data["supporting_documents"]) == MULTI_FILE_COUNT
    assert (
        renewed.attachments.filter(field_key="certificate_documents").count()
        == MULTI_FILE_COUNT
    )
    assert (
        renewed.attachments.filter(field_key="supporting_documents").count()
        == MULTI_FILE_COUNT
    )
    renewed_context = application_context(application, owner)
    too_many_files_form = form_definition.build_form(
        context=renewed_context,
        data={**renewal_data, "certificate_number": "ISO-TOO-MANY-2026"},
        files=MultiValueDict(
            {
                "certificate_documents": [
                    SimpleUploadedFile(
                        f"extra-{index}.pdf",
                        b"extra",
                        content_type="application/pdf",
                    )
                    for index in range(MAX_CERTIFICATE_FILES - 1)
                ],
            },
        ),
        submission_mode="edit",
    )
    assert too_many_files_form.is_valid() is False
    assert "no more than 5 files" in str(
        too_many_files_form.errors["certificate_documents"],
    )

    supporting_to_remove = renewed.attachments.filter(
        field_key="supporting_documents",
        is_current=True,
    ).first()
    assert supporting_to_remove is not None
    edited_form = form_definition.build_form(
        context=renewed_context,
        data={
            **renewal_data,
            "certificate_number": "ISO-EDITED-2026",
            "remove_files__supporting_documents": str(supporting_to_remove.pk),
        },
        files=MultiValueDict(
            {
                "certificate_documents": [
                    SimpleUploadedFile(
                        "new-annexure.pdf",
                        b"new annexure",
                        content_type="application/pdf",
                    ),
                ],
            },
        ),
        submission_mode="edit",
    )
    assert edited_form.is_valid(), edited_form.errors
    edited = save_form_submission(
        application=application,
        form_key="security_certification",
        form=edited_form,
        user=owner,
        submission_mode="edit",
    )
    renewed.refresh_from_db()

    assert renewed.is_current is False
    assert edited.submission_number == RENEWED_SUBMISSION_NUMBER
    assert edited.revision == EDITED_REVISION_NUMBER
    assert edited.data["certificate_number"] == "ISO-EDITED-2026"
    assert len(edited.data["certificate_documents"]) == APPENDED_CERTIFICATE_FILE_COUNT
    assert len(edited.data["supporting_documents"]) == RETAINED_SUPPORTING_FILE_COUNT
    assert set(
        edited.attachments.filter(
            field_key="certificate_documents",
            is_current=True,
        ).values_list("original_name", flat=True),
    ) == {"certificate.pdf", "scope-annexure.pdf", "new-annexure.pdf"}
    assert not edited.attachments.filter(
        original_name=supporting_to_remove.original_name,
        is_current=True,
    ).exists()
    assert edited.attachments.filter(is_current=True).count() == TOTAL_MULTI_FILE_COUNT
    assert renewed.attachments.filter(is_current=True).count() == TOTAL_MULTI_FILE_COUNT
    assert renewed.attachments.filter(pk=supporting_to_remove.pk).exists()
    history = application_context(application, owner).form_history(
        "security_certification",
    )
    assert len(history) == RENEWAL_HISTORY_VERSION_COUNT
    assert (
        len({item.submission_number for item in history}) == RENEWED_SUBMISSION_NUMBER
    )


def test_expired_repeatable_form_is_no_longer_complete(application, actors):
    _organisation, owner, _contributor, _reviewer = actors
    complete_all_forms(application, owner)
    certification = application.submissions.get(
        form_key="security_certification",
        is_current=True,
    )
    certification.valid_until = timezone.localdate() - timedelta(days=1)
    certification.save(update_fields=["valid_until", "updated_at"])

    recalculate_progress(application, user=owner)
    application.refresh_from_db()
    context = application_context(application, owner)
    state = next(
        item
        for item in registry.get(APPLICATION_TYPE).form_states(context)
        if item.definition.key == "security_certification"
    )

    assert state.is_expired is True
    assert state.is_completed is False
    assert application.metadata["completed_forms"] == BASE_REQUIRED_FORM_COUNT - 1
    assert application.metadata["required_forms"] == BASE_REQUIRED_FORM_COUNT


def test_the_evidence_review_covers_every_exit_artifact(application, actors):
    """§4.7: one reviewer judgement over everything the exit turns on, rather
    than a verify action per form that can drift out of step."""
    _organisation, owner, _contributor, reviewer = actors
    complete_all_forms(application, owner)
    application.status = "under_review"
    application.save(update_fields=["status", "updated_at"])

    with pytest.raises(PermissionDenied):
        perform_application_action(
            application=application,
            action_key="review_evidence",
            user=owner,
            cleaned_data={
                "hard_copy_received_on": timezone.localdate(),
                "verified_milestones": [],
            },
        )

    result, _query = perform_application_action(
        application=application,
        action_key="review_evidence",
        user=reviewer,
        cleaned_data={
            "hard_copy_received_on": timezone.localdate(),
            "verified_milestones": [],
        },
    )
    application.refresh_from_db()

    assert str(result.message) == "Evidence reviewed"
    assert application.outcome["reviewed_by"] == reviewer.display_name
    assert set(application.outcome["verified_revisions"]) == set(
        registry.get(APPLICATION_TYPE)
        .get_action("review_evidence")
        .applicable_reviewed_forms(application_context(application, reviewer)),
    )
    assert application.events.filter(action_key="review_evidence").exists()


def test_a_second_review_is_refused_while_nothing_has_changed(application, actors):
    _organisation, owner, _contributor, reviewer = actors
    complete_all_forms(application, owner)
    application.status = "under_review"
    application.save(update_fields=["status", "updated_at"])
    perform_application_action(
        application=application,
        action_key="review_evidence",
        user=reviewer,
        cleaned_data={
            "hard_copy_received_on": timezone.localdate(),
            "verified_milestones": [],
        },
    )

    with pytest.raises(PermissionDenied):
        perform_application_action(
            application=application,
            action_key="review_evidence",
            user=reviewer,
            cleaned_data={
                "hard_copy_received_on": timezone.localdate(),
                "verified_milestones": [],
            },
        )


def test_editing_a_reviewed_form_makes_the_review_stale(application, actors):
    """Staleness stays a revision comparison — the point of recording the
    revision rather than a boolean."""
    _organisation, owner, _contributor, reviewer = actors
    complete_all_forms(application, owner)
    application.status = "under_review"
    application.save(update_fields=["status", "updated_at"])
    perform_application_action(
        application=application,
        action_key="review_evidence",
        user=reviewer,
        cleaned_data={
            "hard_copy_received_on": timezone.localdate(),
            "verified_milestones": [],
        },
    )

    submission = application.submissions.get(form_key="conformance_evidence")
    submission.revision += 1
    submission.save(update_fields=["revision"])

    context = application_context(application, reviewer)
    available, _reason = (
        registry.get(APPLICATION_TYPE)
        .get_action(
            "review_evidence",
        )
        .availability(context)
    )

    assert available is True


def test_applicant_can_open_query_without_changing_application_status(
    application,
    actors,
):
    _organisation, owner, _contributor, reviewer = actors

    _result, query = perform_application_action(
        application=application,
        action_key="ask_review_team",
        user=owner,
        cleaned_data={
            "subject": "Confirm acceptable custodian evidence",
            "message": "Can a signed technology-partner letter be submitted?",
            "related_form": "integration_scope",
        },
    )

    application.refresh_from_db()
    assert application.status == "draft"
    assert query.status == QueryStatus.AWAITING_REVIEWER
    assert query.opened_by == owner
    assert query.assigned_to is None
    assert query.messages.get().author == owner

    post_query_reply(
        thread=query,
        user=reviewer,
        body="Yes, provided it identifies the custodian and product scope.",
    )
    query.refresh_from_db()
    assert query.status == QueryStatus.AWAITING_APPLICANT


def test_full_query_resubmission_and_approval_flow(application, actors):
    _organisation, owner, _contributor, reviewer = actors
    complete_all_forms(application, owner)

    perform_application_action(
        application=application,
        action_key="submit",
        user=owner,
    )
    perform_application_action(
        application=application,
        action_key="start_review",
        user=reviewer,
    )
    _result, query = perform_application_action(
        application=application,
        action_key="raise_query",
        user=reviewer,
        cleaned_data={
            "subject": "Clarify the security assessment scope",
            "message": "Confirm that the gateway callback host was in scope.",
            "related_form": "security_compliance",
            "due_at": timezone.localdate() + timedelta(days=5),
        },
    )
    application.refresh_from_db()
    assert application.status == "changes_requested"
    assert query.status == QueryStatus.AWAITING_APPLICANT

    post_query_reply(
        thread=query,
        user=owner,
        body="The callback host is listed in section 4.2 of the report.",
    )
    query.refresh_from_db()
    assert query.status == QueryStatus.AWAITING_REVIEWER

    perform_application_action(
        application=application,
        action_key="submit",
        user=owner,
    )
    resolve_query(thread=query, user=reviewer)
    perform_application_action(
        application=application,
        action_key="start_review",
        user=reviewer,
    )
    perform_application_action(
        application=application,
        action_key="review_evidence",
        user=reviewer,
        cleaned_data={
            "hard_copy_received_on": timezone.localdate(),
            "verified_milestones": [],
        },
    )
    perform_application_action(
        application=application,
        action_key="approve",
        user=reviewer,
        cleaned_data={
            "approved_milestones": ["m1", "m2", "m3"],
            "effective_date": timezone.localdate() + timedelta(days=1),
            "certificate_reference": "CERT-2026-1001",
            "note": "All evidence verified.",
        },
    )

    application.refresh_from_db()
    assert application.status == "approved"
    assert application.outcome["certificate_reference"] == "CERT-2026-1001"
    # The client id has one home: ProvisionedResource.public_ref.
    assert "production_client_id" not in application.outcome
    assert application.decided_by == reviewer
    assert application.events.filter(action_key="approve").exists()
