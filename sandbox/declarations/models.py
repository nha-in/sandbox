"""Declarations: what an integrator claims to have built, and the evidence.

Legacy modelled this as `self_declaration`, one wide row per application with a
column pair per milestone (`m1_start_date`, `m1_end_date`, ... `nhcx_end_date`),
so adding a track meant a schema change. Here a milestone completion is a row
and the milestone list is catalog data.

Coverage lives on `DeclarationMilestone` rather than an FK here, because an
exit covers the *set* of milestones being taken to production while carrying a
single document bundle — legacy stored that set as a CSV string in
`sd_exit.integration_detail`.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from sandbox.catalog.models import Milestone
from sandbox.declarations.managers import DeclarationDocumentManager
from sandbox.declarations.managers import DeclarationManager
from sandbox.utils.models import BaseModel


class DeclarationKind(models.TextChoices):
    MILESTONE = "MILESTONE", _("Milestone")
    EXIT = "EXIT", _("Exit")


class DeclarationState(models.TextChoices):
    """v0 only ever writes SUBMITTED.

    Nothing reviews a milestone declaration (self-declaration until the
    conformance service lands), and an exit's outcome is currently an
    `Application` transition. The other two exist because open question 3 —
    whether exits are repeatable per milestone set — points at declarations
    carrying their own outcome, and that is cheap now and expensive later.
    """

    SUBMITTED = "SUBMITTED", _("Submitted")
    APPROVED = "APPROVED", _("Approved")
    REJECTED = "REJECTED", _("Rejected")


#: a claim held by one of these may not be superseded by a resubmission
SETTLED_STATES = (DeclarationState.APPROVED,)


class Declaration(BaseModel):
    application = models.ForeignKey(
        "applications.Application",
        on_delete=models.PROTECT,
        related_name="declarations",
    )
    kind = models.CharField(max_length=20, choices=DeclarationKind.choices)
    state = models.CharField(
        max_length=20,
        choices=DeclarationState.choices,
        default=DeclarationState.SUBMITTED,
    )
    # real columns, not payload: reporting filters and sorts on these
    started_on = models.DateField(null=True, blank=True)
    completed_on = models.DateField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    declared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="declarations",
    )

    objects = DeclarationManager()  # type: ignore[misc]

    class Meta:
        default_manager_name = "objects"
        ordering = ["-created_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=DeclarationKind.values),
                name="declarations_declaration_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=DeclarationState.values),
                name="declarations_declaration_state_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(started_on__isnull=True)
                | models.Q(completed_on__isnull=True)
                | models.Q(completed_on__gte=models.F("started_on")),
                name="declarations_declaration_dates_ordered",
            ),
        ]
        indexes = [
            models.Index(
                fields=["application", "-created_date"],
                name="declarations_app_recent_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} declaration for {self.application_id}"


class DeclarationMilestone(models.Model):
    """A claim by one declaration on one milestone.

    Deliberately not a `BaseModel`: no row here is ever addressed from outside,
    and it must not carry `deleted` — supersession is not deletion, and hiding
    superseded claims behind a soft-delete manager would make history invisible
    by default.

    `application` and `kind` are denormalized because a partial unique index can
    only reference columns of its own table. Both are immutable for the life of
    a declaration, so they cannot drift.
    """

    declaration = models.ForeignKey(
        Declaration,
        on_delete=models.PROTECT,
        related_name="milestones",
    )
    milestone = models.ForeignKey(
        Milestone,
        on_delete=models.PROTECT,
        related_name="declaration_claims",
    )
    application = models.ForeignKey(
        "applications.Application",
        on_delete=models.PROTECT,
        related_name="milestone_claims",
    )
    kind = models.CharField(max_length=20, choices=DeclarationKind.choices)
    superseded_by = models.ForeignKey(
        Declaration,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supersedes",
        help_text="Null while this is the current claim on the milestone.",
    )
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "kind", "milestone"],
                condition=models.Q(superseded_by__isnull=True),
                name="declarations_one_current_claim",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=DeclarationKind.values),
                name="declarations_milestone_kind_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["application", "kind"],
                name="declarations_claim_app_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} claim on {self.milestone_id}"


class DeclarationDocument(BaseModel):
    """Evidence. `storage_key` is UUID-based so the bucket cannot be walked."""

    declaration = models.ForeignKey(
        Declaration,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    storage_key = models.CharField(max_length=255, editable=False)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, editable=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="declaration_documents",
    )

    objects = DeclarationDocumentManager()  # type: ignore[misc]

    class Meta:
        default_manager_name = "objects"
        ordering = ["created_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["storage_key"],
                condition=models.Q(deleted=False),
                name="declarations_document_unique_storage_key",
            ),
        ]

    def __str__(self) -> str:
        return self.filename
