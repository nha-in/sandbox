"""Wizard step forms.

One form per step; each renders through `{% ui_field %}`, so nothing here
hand-writes `ui-*` classes into widget attrs. The SANDBOX detail step is not
defined here at all — it comes from the schema registry, so the console renders
exactly what the services validate against.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

from django import forms
from django.utils.translation import gettext_lazy as _

from sandbox.catalog.selectors import districts_for_state
from sandbox.catalog.selectors import is_valid_district_code
from sandbox.catalog.selectors import state_choices
from sandbox.organisations.models import Organisation
from sandbox.organisations.models import Product
from sandbox.organisations.validators import validate_gstin
from sandbox.organisations.validators import validate_name
from sandbox.organisations.validators import validate_pincode
from sandbox.organisations.validators import validate_plain_text

if TYPE_CHECKING:
    from django.db.models import QuerySet

_BLANK = ("", "—")


class OrganisationProfileForm(forms.ModelForm):
    """Who is applying. These facts belong to the organisation, not the payload."""

    # The columns are nullable because an organisation exists before it enrols;
    # enrolment is the point at which a reviewer needs them, so the *form*
    # requires them. GST is the exception — government bodies have none.
    OPTIONAL_FIELDS = ("gst_number", "address_line2")

    class Meta:
        model = Organisation
        fields = [
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
        labels = {
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
            field.required = name not in self.OPTIONAL_FIELDS

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


#: the dropdown value meaning "not one of the listed products". Kept free of
#: underscores so a Tailwind arbitrary variant can select on it.
NEW_PRODUCT = "new"


class ProductStepForm(forms.Form):
    """Which product this application certifies, and what it is called.

    One name box, not two. Its meaning is pinned by `current` — the product it
    was rendered for, which the view reads off the draft and the browser never
    sends. The box renames that product and nothing else.

    That pin is what makes a single box safe with scripting off. The text stays
    put when the dropdown moves, so without it, switching from Scooby to
    another product and pressing Continue would rename the product you had just
    switched *to*.
    """

    product = forms.ChoiceField(label=_("Product"))
    product_name = forms.CharField(
        required=False,
        max_length=255,
        label=_("Product name"),
        validators=[validate_name],
    )

    def __init__(
        self,
        *args,
        available_products: QuerySet[Product],
        current: Product | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.current = current
        self.products = {str(product.pk): product for product in available_products}
        # `project.js` pairs these two so the box follows the dropdown.
        self.fields["product_name"].widget.attrs["data-product-name"] = ""
        if not self.products:
            # A dropdown whose only entry is "a new one" asks nothing.
            del self.fields["product"]
            self.fields["product_name"].required = True
            return
        field = cast("forms.ChoiceField", self.fields["product"])
        field.choices = [
            *((key, product.name) for key, product in self.products.items()),
            (NEW_PRODUCT, _("New product")),
        ]
        field.widget.attrs.update(
            {"data-product-select": "", "data-product-new": NEW_PRODUCT},
        )

    @property
    def new_product_value(self) -> str:
        """So the template knows which option owns the name box."""
        return NEW_PRODUCT

    def clean(self):
        cleaned = super().clean() or {}
        # Absent when the field was dropped above, which means the same thing.
        choice = cleaned.get("product", NEW_PRODUCT)
        name = (cleaned.get("product_name") or "").strip()
        selected = self.products.get(choice)

        if selected is None and not name:
            self.add_error("product_name", _("Name the new product."))

        cleaned["product_name"] = name
        cleaned["selected_product"] = selected
        cleaned["rename_to"] = self._rename_to(selected, name)
        return cleaned

    def _rename_to(self, selected: Product | None, name: str) -> str:
        """The new name, or "" when this submission is not a rename."""
        if self.current is None or selected != self.current:
            return ""
        return name if name and name != self.current.name else ""
