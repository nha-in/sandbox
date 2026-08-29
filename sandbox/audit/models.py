"""Append-only audit trail.

The legacy system had three Kafka publish calls carrying object hashes and
nothing else, so approvals, provisioning and logins were unauditable. This is a
plain table instead: no broker, no outbox, and `object_type` /
`object_external_id` rather than foreign keys, so an audit row keeps meaning
after the thing it describes is gone.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.indexes import BrinIndex
from django.db import models


class AuditEvent(models.Model):
    """One row per notable thing that happened. Never updated, never deleted."""

    occurred_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_external_id = models.UUIDField(null=True, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(
                fields=["object_type", "object_external_id"],
                name="audit_event_object_idx",
            ),
            models.Index(fields=["action"], name="audit_event_action_idx"),
            # The table only ever grows in occurred_at order, so BRIN gives the
            # same range scans as btree for a fraction of the size.
            BrinIndex(fields=["occurred_at"], name="audit_event_occurred_brin"),
        ]

    def __str__(self) -> str:
        return f"{self.action} ({self.occurred_at:%Y-%m-%d %H:%M:%S})"
