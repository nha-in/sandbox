"""Seeds a believable demo world so a fresh checkout is navigable without a VPN.

Applications are driven through the real services — `create_draft`,
`transition()`, `record_review()` — never by writing `state` directly. Seeded
history is therefore legal history: every row has a transition trail and audit
events a reviewer would actually have produced, which is what makes the seed
usable as the e2e fixture and the demo dataset rather than just table filler.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from sandbox.applications.documents import attach_documents
from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationState as S
from sandbox.applications.services import create_draft
from sandbox.applications.services import open_exit
from sandbox.catalog.selectors import districts_for_state
from sandbox.catalog.selectors import state_choices
from sandbox.organisations.models import Membership
from sandbox.organisations.models import MembershipRole
from sandbox.organisations.models import NatureOfEntity
from sandbox.organisations.models import Organisation
from sandbox.organisations.models import OrganisationCategory
from sandbox.organisations.models import OrganisationKind
from sandbox.organisations.models import OrganisationOwnership
from sandbox.organisations.models import Product
from sandbox.programmes.abdm import ABDMExitWorkflow
from sandbox.programmes.abdm import IntegrationIntent
from sandbox.programmes.abdm import PayerCategory
from sandbox.programmes.abdm import SolutionType
from sandbox.workflow import engine
from sandbox.workflow.engine import transition
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.services import record_review

User = get_user_model()

# Natural keys. `--fresh` is scoped to exactly these, so a hand-made row survives.
DEMO_ORG_SLUG = "demo-integrator-network"
OTHER_ORG_SLUG = "rival-health-systems"
SEEDED_ORG_SLUGS = (DEMO_ORG_SLUG, OTHER_ORG_SLUG)

ADMIN_EMAIL = "admin@example.com"
REVIEWER_EMAIL = "reviewer@example.com"
OWNER_EMAIL = "integrator@example.com"
DEVELOPER_EMAIL = "developer@example.com"
OTHER_ORG_EMAIL = "rival@example.com"

DEMO_USERS = [
    (ADMIN_EMAIL, "Sandbox Superuser", {"is_staff": True, "is_superuser": True}),
    (REVIEWER_EMAIL, "Sandbox Reviewer", {"is_staff": True}),
    (OWNER_EMAIL, "Demo Integrator", {}),
    (DEVELOPER_EMAIL, "Demo Developer", {}),
    (OTHER_ORG_EMAIL, "Rival Integrator", {}),
]

# Authority is a permission, never a username string (A5/A6), and permissions
# are per programme: this demo world has one, so both roles are ABDM's.
ADMIN_PERMISSIONS = (
    "view_abdm",
    "review_abdm",
    "approve_abdm",
    "reject_abdm",
    "send_back_abdm",
    "retry_provisioning_abdm",
)
REVIEWER_PERMISSIONS = ("view_abdm", "review_abdm")

DEMO_PAYLOAD = {
    "solution_types": [SolutionType.HMIS.value],
    "integration_intents": [
        IntegrationIntent.ABHA_M1.value,
        IntegrationIntent.HIP_M2.value,
    ],
    "payer_categories": [PayerCategory.TPA.value],
    "use_case_narrative": (
        "Verify a patient's ABHA at OPD registration and share the visit summary "
        "back to their locker."
    ),
}

# Every state, reached the way a real actor would reach it.
#: an action plus the key of the actor performing it; None means a system move
Step = tuple[str, str | None]

#: not a workflow move — the exit bundle A8's `exit_bundle` guard requires
DECLARE_EXIT = "declare_exit"

#: the milestones the demo declares and then exits, matching DEMO_PAYLOAD
DEMO_MILESTONE_KEYS = ("m1", "m2")

DEMO_EVIDENCE = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"

_SUBMITTED: list[Step] = [("SUBMIT", "owner")]
_APPROVED = [*_SUBMITTED, ("APPROVE", "admin")]
_PROVISIONING = [*_APPROVED, ("START_PROVISIONING", None)]
_PROVISIONED = [*_PROVISIONING, ("COMPLETE_PROVISIONING", None)]

PATHS: dict[str, list[Step]] = {
    S.DRAFT: [],
    S.SUBMITTED: _SUBMITTED,
    S.SENT_BACK: [*_SUBMITTED, ("SEND_BACK", "admin")],
    S.WITHDRAWN: [("WITHDRAW", "owner")],
    S.REJECTED: [*_SUBMITTED, ("REJECT", "admin")],
    S.SANDBOX_APPROVED: _APPROVED,
    S.PROVISIONING: _PROVISIONING,
    S.PROVISIONED: _PROVISIONED,
    S.PROVISIONING_FAILED: [*_PROVISIONING, ("FAIL_PROVISIONING", None)],
}

#: Exits are their own applications, so their states are seeded separately —
#: each on a product whose sandbox application is already PROVISIONED.
EXIT_PATHS: dict[str, list[Step]] = {
    "DRAFT": [],
    "SUBMITTED": [("SUBMIT", "owner")],
    "UNDER_REVIEW": [("SUBMIT", "owner"), ("START_REVIEW", "admin")],
    "APPROVED": [
        ("SUBMIT", "owner"),
        ("START_REVIEW", "admin"),
        ("APPROVE", "admin"),
    ],
    "REJECTED": [
        ("SUBMIT", "owner"),
        ("START_REVIEW", "admin"),
        ("REJECT", "admin"),
    ],
    "SENT_BACK": [
        ("SUBMIT", "owner"),
        ("START_REVIEW", "admin"),
        ("SEND_BACK", "admin"),
    ],
}

EXIT_PRODUCT_NAMES: dict[str, str] = {
    "DRAFT": "Jeevan Care Connect",
    "SUBMITTED": "Nidaan Lab Gateway",
    "UNDER_REVIEW": "Setu Health Locker Pro",
    "APPROVED": "Kavach Insurance Hub",
    "REJECTED": "Sahayak PHR",
    "SENT_BACK": "Arogya Bridge Plus",
}

# A second visit to review, so the console tally has more than one round to show.
ROUND_TWO_SLUG = "review-rounds"

#: One product per state, so every state is demonstrable. The slug still names
#: the state (it is the idempotency key); the *name* must not, because the
#: product picker then reads as a list of statuses rather than of products.
PRODUCT_NAMES: dict[str, str] = {
    S.DRAFT: "Aarogya Clinic Suite",
    S.SUBMITTED: "Nirogya HMIS",
    S.SENT_BACK: "Sanjeevani Records",
    S.WITHDRAWN: "Prayaas Teleconsult",
    S.REJECTED: "Vaidya Diagnostics",
    S.SANDBOX_APPROVED: "Setu Health Locker",
    S.PROVISIONING: "Chikitsa OPD",
    S.PROVISIONED: "Swasthya Bridge",
    S.PROVISIONING_FAILED: "Amrit Pharmacy Link",
}
ROUND_TWO_PATH: list[Step] = [
    *_SUBMITTED,
    ("SEND_BACK", "admin"),
    ("SUBMIT", "owner"),
]


def _demo_profile(address_line1: str, city: str, pincode: str) -> dict:
    """A complete profile — organisations can no longer be created without one."""
    state_code, _state_name = state_choices()[0]
    district_code, _district_name = districts_for_state(state_code)[0]
    return {
        "nature_of_entity": NatureOfEntity.COMPANY,
        "ownership": OrganisationOwnership.PRIVATE,
        "category": OrganisationCategory.HEALTHCARE_SOLUTION_PROVIDER,
        "registered_in_india": True,
        "website": "https://example.test",
        "address_line1": address_line1,
        "address_city": city,
        "address_pincode": pincode,
        "lgd_state_code": state_code,
        "lgd_district_code": district_code,
    }


def _evidence(name: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, DEMO_EVIDENCE, content_type="application/pdf")


def _declare_milestones(application, actor):
    """The claims an exit is allowed to cover."""
    for key in DEMO_MILESTONE_KEYS:
        engine.submit_form(
            application=application,
            form_key=f"MILESTONE_{key.upper()}",
            cleaned_data={"completed_on": timezone.localdate()},
            user=actor,
        )


def _open_evidenced_exit(application, actor):
    """An exit application filled in far enough to pass its own gate."""
    exit_application = open_exit(product=application.product, applicant=actor)
    claim = engine.submit_form(
        application=exit_application,
        form_key="EXIT_CLAIM",
        cleaned_data={
            "covers": [key.upper() for key in DEMO_MILESTONE_KEYS],
            "summary": "Functional testing complete on the sandbox gateway.",
        },
        user=actor,
    )
    for kind in ABDMExitWorkflow.form("EXIT_CLAIM").requires_document:
        attach_documents(
            submission=claim,
            uploads=[_evidence(f"{kind.lower()}.pdf")],
            kind=kind,
            actor=actor,
        )
    wasa = engine.submit_form(
        application=exit_application,
        form_key="WASA",
        cleaned_data={
            "start": timezone.localdate() - timedelta(days=30),
            "valid_upto": timezone.localdate() + timedelta(days=335),
        },
        user=actor,
    )
    for kind in ABDMExitWorkflow.form("WASA").requires_document:
        attach_documents(
            submission=wasa,
            uploads=[_evidence(f"{kind.lower()}.pdf")],
            kind=kind,
            actor=actor,
        )
    return exit_application


class Command(BaseCommand):
    help = "Create or refresh the local demo dataset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fresh",
            action="store_true",
            help="Retire previously seeded records before recreating them.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow seeding outside DEBUG (staging snapshots).",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Password for every demo login. Generated and printed if omitted.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            msg = "Refusing to seed outside DEBUG without --force."
            raise CommandError(msg)

        password = options["password"] or secrets.token_urlsafe(9)

        if options["fresh"]:
            self._retire()

        # The demo declares and exits milestones, so it needs the catalog it

        users = self._seed_users(password)
        demo_org, other_org = self._seed_organisations(users)
        self._seed_applications(demo_org, users)
        self._seed_other_org_application(other_org, users)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Seeded demo data."))
        self.stdout.write(
            f"  logins   {', '.join(email for email, _, _ in DEMO_USERS)}",
        )
        self.stdout.write(f"  password {password}")

    # --- fresh ---------------------------------------------------------------

    def _retire(self):
        """Soft-delete what we seeded.

        Not a hard delete: `workflow_transition` PROTECTs both the application
        and the actor, and its rows cannot be deleted at all by design. History
        outlives the demo data that produced it, so `--fresh` retires rows
        rather than erasing them, and re-seeding builds a fresh set alongside.
        """
        organisations = Organisation.objects.filter(slug__in=SEEDED_ORG_SLUGS)
        retired = 0
        for application in Application.objects.filter(
            product__organisation__in=organisations,
        ):
            application.delete()
            retired += 1
        for product in Product.objects.filter(organisation__in=organisations):
            product.delete()
        for membership in Membership.objects.filter(organisation__in=organisations):
            membership.delete()
        for organisation in organisations:
            organisation.delete()
        self.stdout.write(f"Retired {retired} seeded applications and their orgs.")

    # --- users ---------------------------------------------------------------

    def _seed_users(self, password: str) -> dict[str, object]:
        users = {}
        for email, name, flags in DEMO_USERS:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={"name": name, **flags},
            )
            user.set_password(password)
            user.save(update_fields=["password"])
            EmailAddress.objects.update_or_create(
                user=user,
                email=email,
                defaults={"verified": True, "primary": True},
            )
            # demo users must be able to submit, which is gated on both contacts
            if not user.email_verified_at or not user.phone_verified_at:
                user.email_verified_at = user.email_verified_at or timezone.now()
                user.phone = user.phone or "+919999900000"
                user.phone_verified_at = user.phone_verified_at or timezone.now()
                user.save(
                    update_fields=[
                        "email_verified_at",
                        "phone",
                        "phone_verified_at",
                    ],
                )
            users[email] = user
            self.stdout.write(f"{'created' if created else 'exists '} user {email}")

        self._grant(users[ADMIN_EMAIL], ADMIN_PERMISSIONS)
        self._grant(users[REVIEWER_EMAIL], REVIEWER_PERMISSIONS)

        # Re-read: has_perm() caches per instance, and these were just granted.
        return {
            "admin": User.objects.get(pk=users[ADMIN_EMAIL].pk),
            "reviewer": User.objects.get(pk=users[REVIEWER_EMAIL].pk),
            "owner": User.objects.get(pk=users[OWNER_EMAIL].pk),
            "developer": User.objects.get(pk=users[DEVELOPER_EMAIL].pk),
            "rival": User.objects.get(pk=users[OTHER_ORG_EMAIL].pk),
        }

    @staticmethod
    def _grant(user, codenames):
        user.user_permissions.add(
            *Permission.objects.filter(codename__in=codenames),
        )

    # --- organisations -------------------------------------------------------

    def _seed_organisations(self, users):
        demo_org, _ = Organisation.objects.get_or_create(
            slug=DEMO_ORG_SLUG,
            defaults={
                "name": "Demo Integrator Network",
                "kind": OrganisationKind.ORGANIZATION,
                **_demo_profile("12/A, MG Road", "Kochi", "682001"),
            },
        )
        other_org, _ = Organisation.objects.get_or_create(
            slug=OTHER_ORG_SLUG,
            defaults={
                "name": "Rival Health Systems",
                "kind": OrganisationKind.ORGANIZATION,
                **_demo_profile("44, Residency Road", "Bengaluru", "560025"),
            },
        )
        # Orgs seeded before profiles were mandatory would otherwise stay blank.
        for organisation, line1, city, pincode in (
            (demo_org, "12/A, MG Road", "Kochi", "682001"),
            (other_org, "44, Residency Road", "Bengaluru", "560025"),
        ):
            if not organisation.address_line1:
                for field, value in _demo_profile(line1, city, pincode).items():
                    setattr(organisation, field, value)
                organisation.save()

        memberships = (
            (demo_org, users["owner"], MembershipRole.OWNER),
            (demo_org, users["developer"], MembershipRole.DEVELOPER),
            (other_org, users["rival"], MembershipRole.OWNER),
        )
        for organisation, user, role in memberships:
            Membership.objects.get_or_create(
                organisation=organisation,
                user=user,
                defaults={"role": role},
            )
        self.stdout.write(f"organisations: {DEMO_ORG_SLUG}, {OTHER_ORG_SLUG}")
        return demo_org, other_org

    # --- applications --------------------------------------------------------

    def _seed_applications(self, organisation, users):
        for state, path in PATHS.items():
            slug = state.lower().replace("_", "-")
            application = self._application_for(
                organisation,
                slug,
                users["owner"],
                name=PRODUCT_NAMES.get(state, ""),
            )
            if application is None:
                continue
            self._walk(application, path, users)

        self._seed_exits(organisation, users)
        self._seed_review_rounds(organisation, users)

    def _seed_exits(self, organisation, users):
        """Each exit state on its own product, beside a provisioned sandbox."""
        for state, path in EXIT_PATHS.items():
            application = self._application_for(
                organisation,
                f"exit-{state.lower().replace('_', '-')}",
                users["owner"],
                name=EXIT_PRODUCT_NAMES.get(state, ""),
            )
            if application is None:
                continue
            self._walk(application, _PROVISIONED, users)
            _declare_milestones(application, users["owner"])
            exit_application = _open_evidenced_exit(application, users["owner"])
            self._walk(exit_application, path, users)

    def _seed_other_org_application(self, organisation, users):
        """A second org's application, so wrong-org 404s are demonstrable."""
        application = self._application_for(organisation, "rival-hmis", users["rival"])
        if application is not None:
            self._walk(application, _SUBMITTED, {**users, "owner": users["rival"]})

    def _application_for(self, organisation, slug: str, applicant, name: str = ""):
        """Returns None when this slug is already seeded — the idempotency guard."""
        product, created = Product.objects.get_or_create(
            organisation=organisation,
            slug=slug,
            defaults={"name": name or slug.replace("-", " ").title()},
        )
        if not created and Application.objects.filter(product=product).exists():
            return None
        application = create_draft(
            organisation=organisation,
            product=product,
            applicant=applicant,
            workflow_key="ABDM",
        )
        engine.submit_form(
            application=application,
            form_key="REGISTRATION",
            cleaned_data=dict(DEMO_PAYLOAD),
            user=applicant,
        )
        return application

    @staticmethod
    def _walk(application, path, users):
        for action, actor_key in path:
            actor = users[actor_key] if actor_key else None
            decision_data = None
            if action == "APPROVE" and application.workflow_key == "ABDM_EXIT":
                decision_data = {
                    "approved_solution_types": [SolutionType.HMIS.value],
                    "undertaking_hard_copy_received_on": timezone.localdate(),
                    "m1_on_v3_confirmed": True,
                }
            transition(
                application=application,
                action=action,
                actor=actor,
                decision_data=decision_data,
            )

    def _seed_review_rounds(self, organisation, users):
        """One application carrying opinions from two rounds, for the C5 tally."""
        application = self._application_for(
            organisation,
            ROUND_TWO_SLUG,
            users["owner"],
        )
        if application is None:
            return

        transition(application=application, action="SUBMIT", actor=users["owner"])
        record_review(
            application=application,
            reviewer=users["reviewer"],
            decision=ReviewDecision.SEND_BACK,
            comment="Round one: the HIU narrative does not mention consent handling.",
        )
        transition(
            application=application,
            action="SEND_BACK",
            actor=users["admin"],
        )
        transition(application=application, action="SUBMIT", actor=users["owner"])
        record_review(
            application=application,
            reviewer=users["reviewer"],
            decision=ReviewDecision.APPROVE,
            comment="Round two: consent handling described, happy to proceed.",
        )
        record_review(
            application=application,
            reviewer=users["admin"],
            decision=ReviewDecision.REJECT,
            comment="Round two: second opinion — wants the payer flow evidenced first.",
        )
        self.stdout.write("seeded a two-round review with a split tally")
