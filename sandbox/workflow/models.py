"""Append-only transition history.

No `modified_date`, no `deleted`, and the migration revokes UPDATE/DELETE from
the application's database role: the history of who moved an application and
when is evidence, and evidence you can edit is not evidence.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationState
from sandbox.utils.models import BaseModel
from sandbox.workflow.machine import Action


class WorkflowTransition(models.Model):
    application = models.ForeignKey(
        Application,
        on_delete=models.PROTECT,
        related_name="transitions",
    )
    from_state = models.CharField(max_length=30, choices=ApplicationState.choices)
    to_state = models.CharField(max_length=30, choices=ApplicationState.choices)
    action = models.CharField(max_length=30, choices=[(a, a) for a in Action])
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
        constraints = [
            models.CheckConstraint(
                condition=models.Q(from_state__in=ApplicationState.values),
                name="workflow_transition_from_state_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(to_state__in=ApplicationState.values),
                name="workflow_transition_to_state_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(action__in=[a.value for a in Action]),
                name="workflow_transition_action_valid",
            ),
        ]
        permissions = [
            ("approve_application", "Can approve an application"),
            ("reject_application", "Can reject an application"),
            ("review_application", "Can send back or start an exit review"),
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
