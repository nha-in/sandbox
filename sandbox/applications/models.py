"""Applications: one row per workflow instance (plan/09-redesign.md §3).

An exit is a workflow instance, so an exit is a row here too, anchored to the
same `product` as the enrollment it exits from. `workflow_key`, `state` and
`form_key` are plain char columns — their legal values live in the code
registry (`sandbox.workflow.registry`), never in the database.

"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils.translation import gettext_lazy as _

from sandbox.applications.managers import ApplicationDocumentManager
from sandbox.applications.managers import ApplicationManager
from sandbox.applications.managers import FormSubmissionManager
from sandbox.organisations.models import Product
from sandbox.utils.models import BaseModel


class ApplicationState(models.TextChoices):
    """The ABDM sandbox states. Exits have their own, defined by their own
    workflow — labels for display only; the workflow in code is authoritative."""

    DRAFT = "DRAFT", _("Draft")
    SUBMITTED = "SUBMITTED", _("Submitted")
    SANDBOX_APPROVED = "SANDBOX_APPROVED", _("Sandbox approved")
    PROVISIONING = "PROVISIONING", _("Provisioning")
    PROVISIONED = "PROVISIONED", _("Provisioned")
    PROVISIONING_FAILED = "PROVISIONING_FAILED", _("Provisioning failed")
    REJECTED = "REJECTED", _("Rejected")
    SENT_BACK = "SENT_BACK", _("Sent back")
    WITHDRAWN = "WITHDRAWN", _("Withdrawn")


#: states that free the one-in-flight-per-(product, workflow_key) slot.
#: One list serves every workflow: APPROVED is not an ABDM state, and for
#: exits it is exactly what lets January's approved exit sit beside
#: September's in-flight one while forbidding two under review at once.
RESTING_STATES = ("REJECTED", "WITHDRAWN", "APPROVED")


class Application(BaseModel):
    """`state` is denormalized; A5's `transition()` becomes its only writer."""

    reference = models.CharField(max_length=15, editable=False)
    workflow_key = models.CharField(
        max_length=50,
        default="",
        help_text="Resolved against sandbox.workflow.registry — never a CHECK. "
        "Empty only on pre-port rows; the cutover migration backfills it.",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="applications",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="applications",
    )
    state = models.CharField(
        max_length=30,
        choices=ApplicationState.choices,
        default=ApplicationState.DRAFT,
    )
    round = models.PositiveIntegerField(
        default=1,
        help_text="Review cycle; advanced only by round-advancing transitions.",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    objects = ApplicationManager()  # type: ignore[misc]

    class Meta:
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["reference"],
                condition=models.Q(deleted=False),
                name="applications_application_unique_reference",
            ),
            models.UniqueConstraint(
                fields=["product", "workflow_key"],
                condition=models.Q(deleted=False) & ~models.Q(state__in=RESTING_STATES),
                name="applications_one_in_flight_per_product_workflow",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workflow_key", "state"],
                name="applications_wf_state_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.reference


class ApplicationFormSubmission(models.Model):
    """One immutable revision of one form's validated data.

    Append-only like the transition log: data is never rewritten — the only
    column that ever changes on an existing row is `is_current`, flipped when
    a resubmission supersedes it — and rows are never deleted, soft or
    otherwise. Repeatable forms never set `is_current`: they are pure history,
    which is what keeps the single partial unique index serving both kinds.
    """

    external_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )
    application = models.ForeignKey(
        Application,
        on_delete=models.PROTECT,
        related_name="submissions",
    )
    form_key = models.CharField(max_length=50)
    round = models.PositiveIntegerField(
        help_text="Stamped from Application.round at write time.",
    )
    # DjangoJSONEncoder because cleaned_data holds real dates and Decimals
    data = models.JSONField(
        encoder=DjangoJSONEncoder,
        help_text="form.cleaned_data, never raw POST.",
    )
    schema_version = models.PositiveSmallIntegerField(default=1)
    is_current = models.BooleanField(default=False)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="form_submissions",
    )
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = FormSubmissionManager()

    class Meta:
        default_manager_name = "objects"
        ordering = ["-created_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "form_key"],
                condition=models.Q(is_current=True),
                name="applications_one_current_submission",
            ),
        ]
        indexes = [
            models.Index(
                fields=["application", "form_key"],
                name="applications_afs_app_form_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.application_id}/{self.form_key} r{self.round}"


class ApplicationDocument(BaseModel):
    """Evidence for one submission revision.

    Hangs off the submission rather than the application because a WASA
    certificate evidences one round's claim. `storage_key` is UUID-based so
    the bucket cannot be walked; a `sha256` repeated across rounds is a
    reviewer warning, never a block (plan/09-redesign.md §5.3).
    """

    submission = models.ForeignKey(
        ApplicationFormSubmission,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    kind = models.CharField(
        max_length=50,
        help_text="A programme DocumentKind value — resolved in code.",
    )
    storage_key = models.CharField(max_length=255, editable=False)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, editable=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_documents",
    )

    objects = ApplicationDocumentManager()  # type: ignore[misc]

    class Meta:
        default_manager_name = "objects"
        ordering = ["created_date"]
        constraints = [
            # Scoped to the submission, not global: a superseded revision keeps
            # the evidence it was judged on by pointing at the same object, so
            # one `storage_key` legitimately appears once per revision. Twice on
            # one revision is still a double-attach.
            models.UniqueConstraint(
                fields=["submission", "storage_key"],
                condition=models.Q(deleted=False),
                name="applications_document_unique_storage_key",
            ),
        ]

    def __str__(self) -> str:
        return self.filename


class ApplicationReferenceCounter(models.Model):
    """Counter behind `services._next_reference`; skips `BaseModel` because no
    row here is ever addressed from outside."""

    year = models.PositiveIntegerField(unique=True)
    last_value = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.year}: {self.last_value}"
