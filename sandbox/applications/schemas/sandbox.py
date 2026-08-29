"""SANDBOX payload spec, v1.

Choice sets are the legacy lists from
`sandbox-website/src/constants/common-data.js` (`solutionTypeOptions`,
`payersCategories`, `intentForRequestList`).
"""

from __future__ import annotations

from django import forms
from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _

from sandbox.applications.models import ApplicationKind
from sandbox.applications.schemas.registry import register


class SolutionType(TextChoices):
    """Legacy `sd_login.solution_type`."""

    CLINIC_HMIS = "CLINIC_HMIS", _("Clinic HMIS")
    EUA = "EUA", _("End User Applications (EUA)")
    GOVT_PROGRAM = "GOVT_PROGRAM", _("Govt Program")
    GOVT_HMIS = "GOVT_HMIS", _("Govt HMIS")
    GOVT_PHR = "GOVT_PHR", _("Govt PHR")
    HEALTH_LOCKER = "HEALTH_LOCKER", _("Health Locker")
    HEALTHTECH = "HEALTHTECH", _("Healthtech")
    HMIS = "HMIS", _("HMIS")
    INSURANCE = "INSURANCE", _("Insurance")
    LMIS = "LMIS", _("LMIS")
    OTHERS = "OTHERS", _("Others")
    PAYERS = "PAYERS", _("Payers")
    PHARMACY = "PHARMACY", _("Pharmacy")
    PHR = "PHR", _("PHR")
    PROVIDERS = "PROVIDERS", _("Providers")
    TELEMEDICINE = "TELEMEDICINE", _("Telemedicine")


class PayerCategory(TextChoices):
    TPA = "TPA", _("TPA")
    INSURANCE_COMPANY = "INSURANCE_COMPANY", _("Insurance company")


class IntegrationIntent(TextChoices):
    """Legacy `sd_login.field_detail`, built from `intentForRequestDTOs`."""

    ABHA_M1 = "ABHA_M1", _("ABHA Creation/Verification - M1")
    HIP_M2 = "HIP_M2", _("Building Health Information Provider (HIP) - M2")
    HIU_M3 = "HIU_M3", _("Building Health Information User (HIU) - M3")
    HPR_HFR_M4 = "HPR_HFR_M4", _("National Healthcare Provider Registry (HPR/HFR) - M4")
    HEALTH_LOCKER = "HEALTH_LOCKER", _("Health Locker")
    PHR_APP = "PHR_APP", _("PHR App")
    PAYERS = "PAYERS", _("Payers")
    PROVIDERS = "PROVIDERS", _("Providers")
    EUA = "EUA", _("End User Applications (EUA)")
    HSPA = "HSPA", _("Health Service Provider Application (HSPA)")


@register(ApplicationKind.SANDBOX, 1)
class SandboxPayloadV1Form(forms.Form):
    solution_types = forms.MultipleChoiceField(
        choices=SolutionType.choices,
        label=_("Solution type"),
    )
    solution_type_others = forms.CharField(
        required=False,
        max_length=255,
        label=_("Other solution type"),
    )
    integration_intents = forms.MultipleChoiceField(
        choices=IntegrationIntent.choices,
        label=_("Intent for request"),
    )
    # legacy stored NULL here and rendered it as "NA"
    payer_categories = forms.MultipleChoiceField(
        choices=PayerCategory.choices,
        required=False,
        label=_("Payer categories"),
    )
    use_case_narrative = forms.CharField(
        widget=forms.Textarea,
        label=_("Intent behind applying for sandbox"),
    )

    def clean(self):
        super().clean()
        cleaned_data = self.cleaned_data
        solution_types = cleaned_data.get("solution_types") or []
        if SolutionType.OTHERS in solution_types and not cleaned_data.get(
            "solution_type_others",
        ):
            self.add_error(
                "solution_type_others",
                _("Required when 'Others' is selected."),
            )
        return cleaned_data
