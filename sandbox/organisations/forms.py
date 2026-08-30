"""Organisation forms.

The profile lives here, not in the enrolment wizard: these are facts about the
tenant, not about any one application. An organisation cannot be created
incomplete, so nothing downstream has to guard against a half-filled profile.
"""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from sandbox.catalog.selectors import districts_for_state
from sandbox.catalog.selectors import is_valid_district_code
from sandbox.catalog.selectors import state_choices
from sandbox.organisations.models import Organisation
from sandbox.organisations.models import OrganisationKind
from sandbox.organisations.validators import validate_gstin
from sandbox.organisations.validators import validate_name
from sandbox.organisations.validators import validate_pincode
from sandbox.organisations.validators import validate_plain_text

_BLANK = ("", "—")

#: The columns are nullable because they predate C4, and the CHECK constraints
#: still allow "". The form is what makes a profile complete; GSTIN is genuinely
#: optional (government bodies have none) and so is a second address line.
OPTIONAL_FIELDS = ("gst_number", "address_line2")

PROFILE_FIELDS = [
    "nature_of_entity",
    "ownership",
    "category",
    "gst_number",
    "registered_in_india",
    "website",
    "address_line1",
    "address_line2",
    "address_city",
    "address_pincode",
    "lgd_state_code",
    "lgd_district_code",
]

PROFILE_LABELS = {
    "nature_of_entity": _("Nature of entity"),
    "ownership": _("Ownership"),
    "category": _("Category"),
    "gst_number": _("GSTIN"),
    "registered_in_india": _("Registered in India"),
    "website": _("Website"),
    "address_line1": _("Address line 1"),
    "address_line2": _("Address line 2"),
    "address_city": _("City or town"),
    "address_pincode": _("PIN code"),
}


class OrganisationProfileForm(forms.ModelForm):
    """Edit an existing organisation's profile. Any member may."""

    class Meta:
        model = Organisation
        fields = PROFILE_FIELDS
        labels = PROFILE_LABELS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gst_number"].validators.append(validate_gstin)
        self.fields["address_pincode"].validators.append(validate_pincode)
        for name in ("address_line1", "address_line2", "address_city"):
            self.fields[name].validators.append(validate_plain_text)
        self.fields["lgd_state_code"] = forms.ChoiceField(
            choices=[_BLANK, *state_choices()],
            label=_("State"),
        )
        self.fields["lgd_district_code"] = forms.ChoiceField(
            choices=[_BLANK, *districts_for_state(self._selected_state())],
            label=_("District"),
        )
        # `registered_in_india` is a nullable boolean, so "required" has to mean
        # "chose Yes or No" rather than "is truthy".
        self.fields["registered_in_india"] = forms.TypedChoiceField(
            choices=[("", _("—")), ("true", _("Yes")), ("false", _("No"))],
            coerce=lambda value: value == "true",
            label=_("Registered in India"),
        )
        # The model hands this field a Python bool, which matches neither string
        # choice, so a saved answer would render blank on every later visit.
        stored = self.initial.get(
            "registered_in_india",
            self.instance.registered_in_india,
        )
        if stored is not None:
            self.initial["registered_in_india"] = "true" if stored else "false"
        for name, field in self.fields.items():
            field.required = name not in OPTIONAL_FIELDS

    def _selected_state(self) -> str:
        """Bound data first, so a re-render after a validation error keeps the
        district list the user was actually looking at."""
        if self.is_bound:
            return self.data.get("lgd_state_code", "")
        return self.initial.get("lgd_state_code") or self.instance.lgd_state_code

    def clean(self):
        cleaned = super().clean() or {}
        state = cleaned.get("lgd_state_code")
        district = cleaned.get("lgd_district_code")
        # A forged POST can pair any two codes; the dataset decides.
        if state and district and not is_valid_district_code(state, district):
            self.add_error(
                "lgd_district_code",
                _("That district is not in the selected state."),
            )
        return cleaned


class OrganisationCreateForm(OrganisationProfileForm):
    """Identity plus the full profile — an incomplete organisation cannot exist."""

    class Meta(OrganisationProfileForm.Meta):
        fields = ["name", "kind", *PROFILE_FIELDS]
        labels = {
            **PROFILE_LABELS,
            "name": _("Organisation name"),
            "kind": _("Applying as"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].validators.append(validate_name)
        self.fields["kind"].initial = OrganisationKind.ORGANIZATION
