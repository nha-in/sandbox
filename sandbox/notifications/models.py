"""The delivery log — one row per message the portal tried to send.

Two legacy behaviours this replaces, both verified in source:

`notification_audit` stored the **rendered** body in its `message` column, and
`NotificationServiceImpl.sendEmailOTP` rendered the OTP into that body before
saving it. Every verification code the portal ever sent is therefore sitting in
that table in plaintext, unexpiring. `params` here holds render-safe values only
and `services.enqueue` refuses secret-ish keys outright.

Sends were fire-and-forget. The same service wraps its send in
`catch (Exception e)` with the comment "Don't throw the exception as we want to
continue with audit logging", so a failure was written down and then forgotten —
no retry existed anywhere. `state` + `attempts` + `last_error` are what make
B6's retry possible, and what let staff answer "did they get that email?".
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from sandbox.applications.models import Application
from sandbox.utils.models import BaseModel


class Channel(models.TextChoices):
    EMAIL = "EMAIL", _("Email")
    SMS = "SMS", _("SMS")


class MessageState(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    SENT = "SENT", _("Sent")
    FAILED = "FAILED", _("Failed")


class TemplateKey(models.TextChoices):
    """v0's whole vocabulary, re-mapped from the legacy `template-id.*` inventory.

    A CHECK constraint pins it: a typo'd key would otherwise write a row the
    adapter can never map to a gateway template, and only fail at send time.
    """

    SEND_OTP = "send-otp", _("Send OTP")
    SANDBOX_APPROVED = "sandbox-approved", _("Sandbox approved")
    SANDBOX_REJECTED = "sandbox-rejected", _("Sandbox rejected")
    EXIT_SENT_BACK = "exit-sent-back", _("Exit sent back")
    EXIT_REJECTED = "exit-rejected", _("Exit rejected")
    PRODUCTION_APPROVED = "production-approved", _("Production approved")


class Message(BaseModel):
    """Named `Message`, not `NotificationMessage`, for two reasons: the table is
    specified as `notifications_message` (03-database.md §3.4), and
    `ports.NotificationMessage` already means the DTO crossing the port.
    """

    application = models.ForeignKey(
        Application,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="notifications",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    recipient = models.CharField(max_length=254)
    channel = models.CharField(
        max_length=10,
        choices=Channel.choices,
        default=Channel.EMAIL,
    )
    template_key = models.CharField(max_length=50, choices=TemplateKey.choices)
    params = models.JSONField(default=dict, blank=True)
    state = models.CharField(
        max_length=10,
        choices=MessageState.choices,
        default=MessageState.PENDING,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-created_date"]
        indexes = [
            models.Index(
                fields=["state", "created_date"],
                name="notifications_state_idx",
            ),
            models.Index(
                fields=["application", "-created_date"],
                name="notifications_app_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(channel__in=Channel.values),
                name="notifications_message_channel_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=MessageState.values),
                name="notifications_message_state_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(template_key__in=TemplateKey.values),
                name="notifications_message_template_key_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.template_key} -> {self.recipient} ({self.state})"

    # Settling lives here so the Celery path and the inline path cannot drift.

    def note_error(self, code: str, detail: str) -> None:
        """Record a failed attempt but leave the row PENDING for a retry."""
        self.last_error = _error_text(code, detail)
        self.save(update_fields=["last_error", "modified_date"])

    def mark_sent(self, provider_message_id: str = "") -> None:
        self.state = MessageState.SENT
        self.provider_message_id = provider_message_id
        self.last_error = ""
        self.save(
            update_fields=[
                "state",
                "provider_message_id",
                "last_error",
                "modified_date",
            ],
        )

    def mark_failed(self, code: str, detail: str) -> None:
        self.state = MessageState.FAILED
        self.last_error = _error_text(code, detail)
        self.save(update_fields=["state", "last_error", "modified_date"])


def _error_text(code: str, detail: str) -> str:
    """Bounded so a verbose upstream error cannot bloat the table."""
    return f"{code}: {detail}"[: settings.NOTIFICATION_ERROR_MAX_CHARS]
