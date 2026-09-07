from __future__ import annotations

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from sandbox.experiences import permission_keys
from sandbox.experiences.definitions import COMMON_PERMISSIONS
from sandbox.experiences.definitions import ActionResult
from sandbox.experiences.definitions import ApplicationAction
from sandbox.experiences.definitions import ApplicationDefinition
from sandbox.experiences.definitions import ApplicationFormDefinition
from sandbox.experiences.definitions import QueryRequest
from sandbox.experiences.definitions import RoleDefinition
from sandbox.experiences.definitions import StatusDefinition
from sandbox.experiences.models import QueryStatus
from sandbox.experiences.registry import registry
from sandbox.integrations.selectors import provisioning_can_be_retried
from sandbox.integrations.selectors import teardown_is_incomplete
from sandbox.integrations.services import start_deprovisioning
from sandbox.integrations.services import start_provisioning
from sandbox.notifications.hooks import notify
from sandbox.notifications.models import TemplateKey
from sandbox.organisations.grants import record_milestone_grants

from .forms import ApplicantQueryForm
from .forms import ApprovalForm
from .forms import ConformanceEvidenceForm
from .forms import DeclarationForm
from .forms import HealthLockerOperationsForm
from .forms import IntegrationScopeForm
from .forms import MilestoneDeclarationForm
from .forms import OrganisationProfileForm
from .forms import ProductionDetailsForm
from .forms import ProductUseCaseForm
from .forms import RaiseQueryForm
from .forms import RejectionForm
from .forms import ReviewEvidenceForm
from .forms import SecurityCertificationForm
from .forms import SecurityComplianceForm
from .forms import TechnicalReadinessForm
from .gates import exit_gate_blockers
from .reviews import stale_reviews


class OrganisationProfile(ApplicationFormDefinition):
    key = "organisation_profile"
    name = _("Organisation profile")
    description = _("Legal identity and the authorised production-access contact.")
    form_class = OrganisationProfileForm
    allow_updates = True

    @classmethod
    def get_initial(cls, context):
        initial = super().get_initial(context)
        organisation = context.application.organisation
        user = context.user
        defaults = {
            "legal_entity_name": organisation.display_name,
            "registered_address": "",
            "city": organisation.city,
            "state": organisation.state,
            "website": organisation.website,
            "authorised_contact_name": organisation.technical_contact_name
            or user.display_name,
            "authorised_contact_email": organisation.technical_contact_email
            or user.email,
            "authorised_contact_phone": organisation.technical_contact_phone
            or user.phone_number,
        }
        return {**defaults, **initial}

    @classmethod
    def metadata_updates(cls, cleaned_data, context):
        return {
            "legal_entity_name": cleaned_data["legal_entity_name"],
            "contact_email": cleaned_data["authorised_contact_email"],
        }


class ProductUseCase(ApplicationFormDefinition):
    key = "product_use_case"
    name = _("Product and use case")
    description = _("The product, deployment footprint, users, and planned launch.")
    form_class = ProductUseCaseForm
    dependencies = (OrganisationProfile.key,)
    allow_updates = True

    @classmethod
    def metadata_updates(cls, cleaned_data, context):
        return {
            "product_name": cleaned_data["product_name"],
            "product_version": cleaned_data["product_version"],
            "target_go_live_date": cleaned_data["target_go_live_date"],
        }


class IntegrationScope(ApplicationFormDefinition):
    key = "integration_scope"
    name = _("ABDM integration scope")
    description = _("HIP, HIU, health-locker roles and completed sandbox milestones.")
    form_class = IntegrationScopeForm
    dependencies = (ProductUseCase.key,)
    allow_updates = True

    @classmethod
    def metadata_updates(cls, cleaned_data, context):
        return {
            "abdm_roles": cleaned_data["abdm_roles"],
            "sandbox_client_id": cleaned_data["sandbox_client_id"],
        }


class MilestoneDeclaration(ApplicationFormDefinition):
    key = "milestone_declaration"
    name = _("Milestone declaration")
    description = _(
        "Which ABDM milestones are complete, and when each was integrated.",
    )
    form_class = MilestoneDeclarationForm
    dependencies = (IntegrationScope.key,)
    allow_updates = True

    @classmethod
    def metadata_updates(cls, cleaned_data, context):
        return {"milestones": cleaned_data["milestones"]}


class HealthLockerOperations(ApplicationFormDefinition):
    key = "health_locker_operations"
    name = _("Health locker operations")
    description = _(
        "Operational controls required only when health locker access is requested.",
    )
    form_class = HealthLockerOperationsForm
    dependencies = (IntegrationScope.key,)
    allow_updates = True

    @classmethod
    def is_applicable(cls, context):
        integration_scope = context.form_data(IntegrationScope.key)
        return "health_locker" in integration_scope.get("abdm_roles", [])

    @classmethod
    def metadata_updates(cls, cleaned_data, context):
        return {
            "health_locker_name": cleaned_data["locker_name"],
            "health_locker_custodian_model": cleaned_data["custodian_model"],
        }


class TechnicalReadiness(ApplicationFormDefinition):
    key = "technical_readiness"
    name = _("Technical readiness")
    description = _(
        "Production endpoints, network controls, reliability, and escalation.",
    )
    form_class = TechnicalReadinessForm
    dependencies = (IntegrationScope.key,)
    allow_updates = True


class SecurityCompliance(ApplicationFormDefinition):
    key = "security_compliance"
    name = _("Security and privacy")
    description = _("Assessment evidence and operational data-protection controls.")
    form_class = SecurityComplianceForm
    dependencies = (TechnicalReadiness.key,)
    allow_updates = True

    @classmethod
    def metadata_updates(cls, cleaned_data, context):
        return {
            "security_assessment_date": cleaned_data["assessment_date"],
            "security_assessment_agency": cleaned_data["security_assessment_agency"],
        }


class SecurityCertification(ApplicationFormDefinition):
    key = "security_certification"
    name = _("Security certification")
    description = _(
        "Time-bound security certification with retained renewal history and "
        "supporting evidence.",
    )
    form_class = SecurityCertificationForm
    dependencies = (SecurityCompliance.key,)
    allow_updates = True
    repeatable = True
    valid_until_field = "expires_on"
    renewal_window_days = 45
    editable_statuses = frozenset(
        {
            "draft",
            "submitted",
            "under_review",
            "changes_requested",
            "revision_submitted",
            "approved",
        },
    )

    @classmethod
    def metadata_updates(cls, cleaned_data, context):
        return {
            "security_certification_type": cleaned_data["certification_type"],
            "security_certification_number": cleaned_data["certificate_number"],
            "security_certification_valid_until": cleaned_data["expires_on"],
        }


class ConformanceEvidence(ApplicationFormDefinition):
    key = "conformance_evidence"
    name = _("Conformance evidence")
    description = _("Functional testing report, undertaking, demo, and request traces.")
    form_class = ConformanceEvidenceForm
    dependencies = (SecurityCertification.key,)
    allow_updates = True

    @classmethod
    def metadata_updates(cls, cleaned_data, context):
        return {
            "tested_milestones": cleaned_data["tested_milestones"],
            "functional_certificate_number": cleaned_data[
                "functional_certificate_number"
            ],
        }


class Declaration(ApplicationFormDefinition):
    key = "declaration"
    name = _("Authorised declaration")
    description = _("Final declarations and accountable signatory details.")
    form_class = DeclarationForm
    dependencies = (ConformanceEvidence.key,)
    allow_updates = False

    @classmethod
    def metadata_updates(cls, cleaned_data, context):
        return {
            "signatory_name": cleaned_data["signatory_name"],
            "declaration_date": cleaned_data["declaration_date"],
        }


class WithdrawApplication(ApplicationAction):
    """Pull an application before a decision.

    The `withdrawn` status and the `application.withdraw` permission both
    already existed with no action reaching either (plan 12 §6 E2). Terminal: a
    fresh application is the way back, which is what keeps the withdrawn one
    readable rather than reopened.
    """

    key = "withdraw"
    name = _("Withdraw application")
    description = _("Pull this application out of review. This cannot be undone.")
    required_permissions = {"perform": permission_keys.WITHDRAW_APPLICATION}
    allowed_statuses = frozenset(
        {
            "draft",
            "submitted",
            "under_review",
            "changes_requested",
            "revision_submitted",
        },
    )

    @classmethod
    def perform(cls, context, cleaned_data):
        return ActionResult(
            message=_("Application withdrawn"),
            new_status="withdrawn",
            outcome_updates={
                "withdrawn_by": context.user.pk,
                "withdrawn_reason": str(cleaned_data.get("note", "")),
            },
            effects=(lambda application, user: start_deprovisioning(application),),
        )


class ProductionDetails(ApplicationFormDefinition):
    """Recorded by the review team once production access exists (§4.8).

    In scope for the application, but never the applicant's to fill: `view`
    follows `edit`, so it stays off their checklist until it holds a value.
    """

    key = "production_details"
    name = _("Production details")
    description = _("The production client issued outside the sandbox.")
    form_class = ProductionDetailsForm
    required_permissions = {"edit": permission_keys.APPROVE_APPLICATION}
    editable_statuses = frozenset({"approved"})
    allow_updates = True
    required = False


class SubmitApplication(ApplicationAction):
    key = "submit"
    name = _("Submit for review")
    description = _("Lock the completed application into the OHC review queue.")
    required_permissions = {"perform": permission_keys.SUBMIT_APPLICATION}
    allowed_statuses = frozenset({"draft", "changes_requested"})

    @classmethod
    def extra_availability(cls, context):
        definition = registry.get(context.application.application_type)
        if not definition.required_forms_complete(context):
            return False, _("Complete every required form before submitting.")
        has_unanswered_query = context.application.query_threads.filter(
            status=QueryStatus.AWAITING_APPLICANT,
        ).exists()
        if context.application.status == "changes_requested" and has_unanswered_query:
            return False, _("Respond to every open query before resubmitting.")
        blockers = exit_gate_blockers(context)
        if blockers:
            return False, blockers[0]
        return True, ""

    @classmethod
    def perform(cls, context, cleaned_data):
        is_revision = context.application.status == "changes_requested"
        count = int(context.application.metadata.get("submission_count", 0)) + 1
        return ActionResult(
            message=_("Application resubmitted")
            if is_revision
            else _("Application submitted"),
            new_status="revision_submitted" if is_revision else "submitted",
            metadata_updates={
                "submission_count": count,
                "last_submitted_by": context.user.display_name,
            },
        )


class AskReviewTeam(ApplicationAction):
    key = "ask_review_team"
    name = _("Ask review team")
    description = _(
        "Open a question about this application or request support from the "
        "review team.",
    )
    required_permissions = {"perform": permission_keys.OPEN_QUERY}
    allowed_statuses = frozenset(
        {
            "draft",
            "submitted",
            "under_review",
            "changes_requested",
            "revision_submitted",
            "approved",
            "rejected",
        },
    )
    form_class = ApplicantQueryForm

    @classmethod
    def perform(cls, context, cleaned_data):
        return ActionResult(
            message=_("Question sent to the review team"),
            query=QueryRequest(
                subject=cleaned_data["subject"],
                message=cleaned_data["message"],
                form_key=cleaned_data.get("related_form", ""),
                initial_status=QueryStatus.AWAITING_REVIEWER,
            ),
        )


class StartReview(ApplicationAction):
    key = "start_review"
    name = _("Start review")
    description = _("Move the submitted application into active review.")
    required_permissions = {"perform": permission_keys.REVIEW_APPLICATION}
    allowed_statuses = frozenset({"submitted", "revision_submitted"})

    @classmethod
    def perform(cls, context, cleaned_data):
        return ActionResult(
            message=_("Review started"),
            new_status="under_review",
            metadata_updates={"review_started_by": context.user.display_name},
        )


class RaiseQuery(ApplicationAction):
    key = "raise_query"
    name = _("Raise query")
    description = _("Request clarification, corrected data, or replacement evidence.")
    required_permissions = {"perform": permission_keys.RAISE_QUERY}
    allowed_statuses = frozenset(
        {"submitted", "under_review", "changes_requested", "revision_submitted"},
    )
    form_class = RaiseQueryForm

    @classmethod
    def perform(cls, context, cleaned_data):
        return ActionResult(
            message=_("Query raised"),
            new_status="changes_requested",
            query=QueryRequest(
                subject=cleaned_data["subject"],
                message=cleaned_data["message"],
                form_key=cleaned_data.get("related_form", ""),
                due_at=cleaned_data.get("due_at"),
            ),
            effects=(notify(TemplateKey.EXIT_SENT_BACK),),
        )


class ReviewEvidence(ApplicationAction):
    """One reviewer judgement over everything the exit turns on (§4.7).

    `verified_revisions` lives on the application rather than on each
    submission: review is application-level, and staleness stays a revision
    comparison — an applicant editing a reviewed form makes its entry stale.
    """

    key = "review_evidence"
    name = _("Record evidence review")
    description = _("Confirm the declared milestones and their exit artifacts.")
    required_permissions = {"perform": permission_keys.REVIEW_APPLICATION}
    is_internal = True
    allowed_statuses = frozenset({"under_review", "revision_submitted"})
    form_class = ReviewEvidenceForm

    #: §3.2's four exit artifacts, plus the declaration they are evidence for.
    reviewed_forms = (
        "milestone_declaration",
        "security_compliance",
        "security_certification",
        "conformance_evidence",
        "declaration",
    )

    @classmethod
    def applicable_reviewed_forms(cls, context) -> tuple[str, ...]:
        """Every entry applies today. Filtered anyway: a conditional form added
        here would otherwise read as permanently unreviewed, blocking approval
        for ever."""
        definition = registry.get(context.application.application_type)
        return tuple(
            key
            for key in cls.reviewed_forms
            if definition.get_form(key).is_applicable(context)
        )

    @classmethod
    def extra_availability(cls, context):
        missing = [
            key
            for key in cls.applicable_reviewed_forms(context)
            if not context.has_completed(key)
        ]
        if missing:
            return False, _("Every exit artifact must be submitted first.")
        if not stale_reviews(context):
            return False, _("The current evidence is already reviewed.")
        return True, ""

    @classmethod
    def perform(cls, context, cleaned_data):
        verified = tuple(cleaned_data["verified_milestones"])
        return ActionResult(
            message=_("Evidence reviewed"),
            outcome_updates={
                "verified_revisions": {
                    key: context.submissions[key].revision
                    for key in cls.applicable_reviewed_forms(context)
                    if key in context.submissions
                },
                "verified_milestones": list(verified),
                "hard_copy_received_on": cleaned_data["hard_copy_received_on"],
                "reviewed_by": context.user.display_name,
                "reviewed_at": timezone.now(),
            },
            effects=(
                lambda application, _user: record_milestone_grants(
                    application,
                    verified,
                ),
            ),
        )


class ApproveApplication(ApplicationAction):
    key = "approve"
    name = _("Approve production access")
    description = _("Record approved milestones and production credentials reference.")
    required_permissions = {"perform": permission_keys.APPROVE_APPLICATION}
    allowed_statuses = frozenset({"under_review", "revision_submitted"})
    form_class = ApprovalForm

    @classmethod
    def extra_availability(cls, context):
        if context.application.query_threads.exclude(
            status=QueryStatus.RESOLVED,
        ).exists():
            return False, _("Resolve every application query before approval.")
        if stale_reviews(context):
            return False, _("Review the evidence before approving.")
        return True, ""

    @classmethod
    def perform(cls, context, cleaned_data):
        return ActionResult(
            message=_("Production access approved"),
            new_status="approved",
            outcome_updates={
                "decision": "approved",
                "effective_date": cleaned_data["effective_date"],
                "certificate_reference": cleaned_data["certificate_reference"],
                "decision_note": cleaned_data.get("note", ""),
                "decided_by": context.user.display_name,
            },
            effects=(
                notify(TemplateKey.PRODUCTION_APPROVED),
                lambda application, user: start_provisioning(application),
            ),
        )


class RejectApplication(ApplicationAction):
    key = "reject"
    name = _("Reject application")
    description = _("Record a final rejection with clear reasons and next steps.")
    required_permissions = {"perform": permission_keys.REJECT_APPLICATION}
    allowed_statuses = frozenset(
        {"submitted", "under_review", "changes_requested", "revision_submitted"},
    )
    form_class = RejectionForm
    style = "destructive"

    @classmethod
    def perform(cls, context, cleaned_data):
        return ActionResult(
            message=_("Application rejected"),
            new_status="rejected",
            outcome_updates={
                "decision": "rejected",
                "reason": cleaned_data["reason"],
                "details": cleaned_data["details"],
                "decision_note": cleaned_data.get("note", ""),
                "decided_by": context.user.display_name,
            },
            effects=(
                notify(TemplateKey.EXIT_REJECTED),
                lambda application, user: start_deprovisioning(application),
            ),
        )


class RetryProvisioning(ApplicationAction):
    """Ask the three systems again for whatever the failed attempt did not create.

    It is the same chain, not a repair: every system whose ledger row is already
    ACTIVE is skipped, so a run that died at the bridge creates only the bridge.

    An action rather than a console button calling `enqueue_chain` directly,
    because that is what gives the retry a permission to check and an
    `ApplicationEvent` naming who asked — the two things it lost when
    `sandbox/workflow/` went.
    """

    key = "retry_provisioning"
    name = _("Retry provisioning")
    description = _("Re-run credential provisioning after a failed attempt.")
    required_permissions = {"perform": permission_keys.RETRY_PROVISIONING}
    is_internal = True
    allowed_statuses = frozenset({"approved"})

    @classmethod
    def extra_availability(cls, context):
        if not provisioning_can_be_retried(context.application):
            return False, _("The last provisioning attempt did not fail.")
        return True, ""

    @classmethod
    def perform(cls, context, cleaned_data):
        return ActionResult(
            message=_("Provisioning retried"),
            effects=(start_provisioning,),
        )


class RetryDeprovisioning(ApplicationAction):
    """Re-run teardown while anything is still switched on.

    Offered for as long as the ledger says a credential survives the decision:
    a rejected integrator holding a live client is the failure this exists to
    close, and unlike provisioning it is worth re-asking even after a run that
    reported no error, because teardown does not stop at its first failure.
    """

    key = "retry_deprovisioning"
    name = _("Retry teardown")
    description = _(
        "Re-run credential teardown for a rejected or withdrawn application.",
    )
    required_permissions = {"perform": permission_keys.RETRY_PROVISIONING}
    is_internal = True
    allowed_statuses = frozenset({"rejected", "withdrawn"})
    style = "destructive"

    @classmethod
    def extra_availability(cls, context):
        if not teardown_is_incomplete(context.application):
            return False, _("Nothing is still provisioned for this application.")
        return True, ""

    @classmethod
    def perform(cls, context, cleaned_data):
        return ActionResult(
            message=_("Teardown retried"),
            effects=(lambda application, user: start_deprovisioning(application),),
        )


@registry.register
class ABDMProductionAccess(ApplicationDefinition):
    key = "abdm_production_access"
    name = _("ABDM production access")
    description = _(
        "A full sandbox-exit and production-access review for an ABDM-integrated "
        "digital health product.",
    )
    reference_prefix = "ABDM"
    statuses = (
        StatusDefinition("draft", _("Draft"), _("Forms are being completed."), "muted"),
        StatusDefinition(
            "submitted",
            _("Submitted"),
            _("Waiting for a reviewer to begin."),
            "info",
        ),
        StatusDefinition(
            "under_review",
            _("Under review"),
            _("The OHC team is reviewing the evidence."),
            "warning",
        ),
        StatusDefinition(
            "changes_requested",
            _("Changes requested"),
            _("One or more reviewer queries need a response."),
            "destructive",
        ),
        StatusDefinition(
            "revision_submitted",
            _("Revision submitted"),
            _("Updated evidence is ready for review."),
            "info",
        ),
        StatusDefinition(
            "approved",
            _("Approved"),
            _("Production access has been approved."),
            "success",
            terminal=True,
        ),
        StatusDefinition(
            "rejected",
            _("Rejected"),
            _("A final rejection has been recorded."),
            "destructive",
            terminal=True,
        ),
        StatusDefinition(
            "withdrawn",
            _("Withdrawn"),
            _("The applicant withdrew this application."),
            "muted",
            terminal=True,
        ),
    )
    permissions = COMMON_PERMISSIONS
    roles = (
        RoleDefinition(
            "applicant_owner",
            _("Application owner"),
            _("Completes, submits, and manages applicant access."),
            "organisation",
            frozenset(
                {
                    permission_keys.VIEW_APPLICATION,
                    permission_keys.EDIT_FORMS,
                    permission_keys.SUBMIT_APPLICATION,
                    permission_keys.VIEW_QUERIES,
                    permission_keys.OPEN_QUERY,
                    permission_keys.RESPOND_QUERIES,
                    permission_keys.MANAGE_APPLICANT_ACCESS,
                    permission_keys.WITHDRAW_APPLICATION,
                },
            ),
        ),
        RoleDefinition(
            "applicant_submitter",
            _("Applicant submitter"),
            _("Completes forms, answers queries, and can submit."),
            "organisation",
            frozenset(
                {
                    permission_keys.VIEW_APPLICATION,
                    permission_keys.EDIT_FORMS,
                    permission_keys.SUBMIT_APPLICATION,
                    permission_keys.VIEW_QUERIES,
                    permission_keys.OPEN_QUERY,
                    permission_keys.RESPOND_QUERIES,
                },
            ),
        ),
        RoleDefinition(
            "applicant_contributor",
            _("Applicant contributor"),
            _("Completes forms and answers queries without submitting."),
            "organisation",
            frozenset(
                {
                    permission_keys.VIEW_APPLICATION,
                    permission_keys.EDIT_FORMS,
                    permission_keys.VIEW_QUERIES,
                    permission_keys.OPEN_QUERY,
                    permission_keys.RESPOND_QUERIES,
                },
            ),
        ),
        RoleDefinition(
            "applicant_viewer",
            _("Applicant viewer"),
            _("Read-only access to application data and queries."),
            "organisation",
            frozenset(
                {
                    permission_keys.VIEW_APPLICATION,
                    permission_keys.VIEW_QUERIES,
                },
            ),
        ),
    )
    forms = (
        OrganisationProfile,
        ProductUseCase,
        IntegrationScope,
        MilestoneDeclaration,
        HealthLockerOperations,
        TechnicalReadiness,
        SecurityCompliance,
        SecurityCertification,
        ConformanceEvidence,
        Declaration,
        ProductionDetails,
    )
    actions = (
        SubmitApplication,
        WithdrawApplication,
        AskReviewTeam,
        StartReview,
        RaiseQuery,
        ReviewEvidence,
        ApproveApplication,
        RejectApplication,
        RetryProvisioning,
        RetryDeprovisioning,
    )
