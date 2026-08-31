"""Append-only transition history.

No `modified_date`, no `deleted`, and the migration revokes UPDATE/DELETE from
the application's database role: the history of who moved an application and
when is evidence, and evidence you can edit is not evidence.

`from_state` / `to_state` / `action` are plain char columns — their legal
values come from the workflow class in code (plan/09-redesign.md §2), and the
registry-sanity test asserts every persisted value is known there.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from sandbox.applications.models import Application
from sandbox.utils.models import BaseModel


class WorkflowTransition(models.Model):
    application = models.ForeignKey(
        Application,
        on_delete=models.PROTECT,
        related_name="transitions",
    )
    from_state = models.CharField(max_length=40)
    to_state = models.CharField(max_length=40)
    action = models.CharField(max_length=40)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_transitions",
        help_text="Null for system moves such as chain completion.",
    )
    comment = models.TextField(blank=True)
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_date"]
        indexes = [
            models.Index(
                fields=["application", "-created_date"],
                name="workflow_transition_app_idx",
            ),
        ]
        permissions = [
            ("approve_application", "Can approve an application"),
            ("reject_application", "Can reject an application"),
            ("send_back_application", "Can return an application to the applicant"),
            ("review_application", "Can record a review (moves nothing)"),
            ("retry_provisioning", "Can retry a failed provisioning chain"),
        ]

    def __str__(self) -> str:
        return f"{self.application_id}: {self.from_state} -> {self.to_state}"


class ReviewDecision(models.TextChoices):
    APPROVE = "APPROVE", _("Approve")
    REJECT = "REJECT", _("Reject")
    SEND_BACK = "SEND_BACK", _("Send back")


class WorkflowReview(BaseModel):
    """A reviewer's opinion. Advisory: only `transition()` moves the application.

    Legacy kept these in fifteen columns on a wide row keyed by JWT username
    string, so a second opinion overwrote the first and authority was a string
    comparison. Rows plus a permission check replace both.
    """

    application = models.ForeignKey(
        Application,
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    round = models.PositiveIntegerField(default=1)
    decision = models.CharField(max_length=20, choices=ReviewDecision.choices)
    comment = models.TextField(blank=True)
    decided_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-decided_at"]
        indexes = [
            models.Index(
                fields=["application", "round"],
                name="workflow_review_round_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "reviewer", "round"],
                condition=models.Q(deleted=False),
                name="workflow_review_unique_per_round",
            ),
            models.CheckConstraint(
                condition=models.Q(decision__in=ReviewDecision.values),
                name="workflow_review_decision_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.application_id} r{self.round}: {self.decision}"
