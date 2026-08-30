"""Forms for the declaration screens.

Deliberately thin: A7's services own every rule that matters, and its
`validators` own every rule about a file. These collect input, name the fields,
and hand the raw uploads on — a form that re-checked signatures here would be a
second copy of the rule, and the two would drift.
"""

from __future__ import annotations

from typing import cast

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Django has no multi-file field; this is the documented way to make one."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        uploads = data if isinstance(data, list | tuple) else [data]
        return [super(MultipleFileField, self).clean(item, initial) for item in uploads]


class _EvidenceForm(forms.Form):
    """Shared upload field. Limits come from settings so the hint cannot lie."""

    documents = MultipleFileField(
        required=False,
        label=_("Supporting documents"),
    )

    @property
    def upload_hint(self) -> str:
        extensions = ", ".join(settings.UPLOAD_ALLOWED_EXTENSIONS)
        megabytes = settings.UPLOAD_MAX_BYTES // (1024 * 1024)
        return str(
            _("%(extensions)s, up to %(megabytes)s MB each, %(count)s files at most")
            % {
                "extensions": extensions,
                "megabytes": megabytes,
                "count": settings.UPLOAD_MAX_FILES,
            },
        )


class MilestoneDeclarationForm(_EvidenceForm):
    """Declare one milestone complete. The milestone itself comes from the URL."""

    started_on = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Started on"),
    )
    completed_on = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Completed on"),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label=_("What you built and how you tested it"),
    )

    def payload(self) -> dict[str, str]:
        notes = self.cleaned_data.get("notes", "").strip()
        return {"notes": notes} if notes else {}


class ExitDeclarationForm(_EvidenceForm):
    """Request production. `milestones` is bound to what has been declared."""

    milestones = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        label=_("Milestones to take to production"),
    )
    summary = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        label=_("Summary of your integration"),
    )

    def __init__(self, *args, choices=(), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        field = cast("forms.MultipleChoiceField", self.fields["milestones"])
        field.choices = list(choices)

    def payload(self) -> dict[str, str]:
        return {"summary": self.cleaned_data["summary"].strip()}
