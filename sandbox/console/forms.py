"""Console forms. Validation only — every write goes through a Lane A service."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from sandbox.workflow.machine import Action
from sandbox.workflow.models import ReviewDecision

#: decisions that must be explained before they are recorded
_COMMENT_REQUIRED_ACTIONS = frozenset(
    {
        Action.REJECT,
        Action.SEND_BACK,
        Action.REJECT_EXIT,
        Action.SEND_BACK_EXIT,
    },
)


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=ReviewDecision.choices,
        label=_("Decision"),
    )
    comment = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        label=_("Comment"),
        help_text=_("The single home for this text — it is never copied elsewhere."),
    )


class DecisionForm(forms.Form):
    """Approve / reject / send back. The comment rides on the review row."""

    action = forms.ChoiceField(choices=[(a, a) for a in Action])
    comment = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label=_("Comment"),
    )

    def clean(self):
        cleaned = super().clean() or {}
        action = cleaned.get("action")
        if action in _COMMENT_REQUIRED_ACTIONS and not cleaned.get("comment"):
            self.add_error(
                "comment",
                _(
                    "Say why — a rejection or send-back without a reason "
                    "is not reviewable.",
                ),
            )
        return cleaned
