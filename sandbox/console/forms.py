"""Console forms. Validation only — every write goes through a Lane A service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import forms
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.utils.translation import gettext_lazy as _

from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.registry import permission_labels
from sandbox.workflow.registry import programme_for_permission

if TYPE_CHECKING:
    from sandbox.users.models import User

#: decisions that must be explained before they are recorded
_COMMENT_REQUIRED_ACTIONS = frozenset({"REJECT", "SEND_BACK"})


def assignable_permissions():
    """What a role may grant: the programmes' permissions, and only those.

    `manage_roles` is deliberately absent. It is authority over authority, so
    offering it here would let anyone who can edit a role grant themselves
    every other one — the standard RBAC escalation. It comes from a superuser
    through the Django admin instead.
    """
    codenames = [name.split(".", 1)[1] for name in permission_labels()]
    return Permission.objects.filter(
        content_type__app_label="workflow",
        codename__in=codenames,
    ).order_by("codename")


class RoleForm(forms.ModelForm):
    """A role is a name and a set of permissions — which is what a Group is.

    Membership is not here. Twenty console users make a checkbox list nobody
    can read, and the question people actually ask is "what may this person
    do", not "who is in this role". That lives on the user page.
    """

    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label=_("Permissions"),
    )

    class Meta:
        model = Group
        fields = ("name",)
        labels = {"name": _("Role name")}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["permissions"].queryset = assignable_permissions()  # type: ignore[attr-defined]

    def permission_groups(self) -> list[dict]:
        """The checkboxes, grouped by programme.

        Rendered from data rather than by iterating the widget: Django flattens
        grouped choices back out again, and a flat list is exactly what makes a
        two-programme portal unreadable.
        """
        chosen = {str(value) for value in (self["permissions"].value() or [])}
        groups: dict[str, list[dict]] = {}
        for permission in self.fields["permissions"].queryset:  # type: ignore[attr-defined]
            programme = programme_for_permission(f"workflow.{permission.codename}")
            groups.setdefault(programme.upper(), []).append(
                {
                    "id": permission.pk,
                    "label": permission.name,
                    "checked": str(permission.pk) in chosen,
                },
            )
        return [
            {"programme": programme, "permissions": permissions}
            for programme, permissions in sorted(groups.items())
        ]


class UserRolesForm(forms.Form):
    """Which roles this person holds. The direction people actually work in."""

    roles = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all().order_by("name"),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label=_("Roles"),
    )

    def __init__(self, *args, user: User | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["roles"].initial = user.groups.all()


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
    """Approve / reject / send back. The comment rides on the review row.

    `action` is a plain string: the legal set depends on the workflow the
    application belongs to, and the engine is what refuses an illegal move.
    """

    action = forms.CharField(max_length=50)
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
