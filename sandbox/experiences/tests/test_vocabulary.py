"""The registry's legal values (plan 12 §6 D2, D3, D5, D6).

Renaming a key orphans every row holding it, so the sets are pinned here rather
than left to whoever edits the form next.
"""

from __future__ import annotations

from sandbox.experiences.abdm.forms import ABDM_ROLES
from sandbox.experiences.abdm.forms import MILESTONES
from sandbox.experiences.abdm.forms import IntegrationScopeForm
from sandbox.experiences.abdm.forms import SecurityCertificationForm
from sandbox.experiences.abdm.forms import SecurityComplianceForm

HEALTH_INFORMATION_TYPE_COUNT = 8


def _values(choices) -> list[str]:
    return [value for value, _label in choices]


def test_the_eight_health_information_types():
    """D2: six to eight. `Invoice` is what a pharmacy owes, and a category
    matrix keys on these, so a missing one is silently unselectable."""
    field = IntegrationScopeForm().fields["health_information_types"]

    assert len(field.choices) == HEALTH_INFORMATION_TYPE_COUNT
    assert {"health_document", "invoice"} <= set(_values(field.choices))


def test_the_abdm_roles():
    """D5 adds `hrp` — legacy's "Health Repository Provider". `phr` comes with
    it: §3.1 names PHR an ABDM role and this list had only health locker."""
    assert _values(ABDM_ROLES) == ["hip", "hiu", "hrp", "phr", "health_locker"]


def test_the_four_milestones():
    """D6. Derived from the enum, so this pins that the derivation holds."""
    assert _values(MILESTONES) == ["m1", "m2", "m3", "m4"]


def test_the_certificate_number_has_one_home():
    """D3: the compliance form's copy carried neither expiry nor renewal, so
    two fields could disagree about the same certificate."""
    assert "wasa_certificate_number" not in SecurityComplianceForm().fields

    certification = SecurityCertificationForm().fields
    assert "certificate_number" in certification
    assert "expires_on" in certification
