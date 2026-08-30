"""Ledger schema guarantees (B1 deliverable 3).

The uniqueness rule is the idempotency backstop for B7: a retried provisioning
chain must not be able to create a second Keycloak client for the same
application. Asserted against the database, not the model layer, because that is
where a concurrent retry would collide.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.db import transaction
from django.db.models import ProtectedError

from sandbox.applications.models import Application
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedResourceState
from sandbox.integrations.models import ProvisionedSystem

pytestmark = pytest.mark.django_db

LIVE_PLUS_RETIRED = 2


def _resource(**overrides) -> ProvisionedResource:
    defaults = {
        "application": overrides.pop("application", None) or ApplicationFactory(),
        "system": ProvisionedSystem.KEYCLOAK,
        "external_ref": "SBXID_1001",
    }
    return ProvisionedResource.objects.create(**{**defaults, **overrides})


def test_one_live_resource_per_application_and_system():
    first = _resource()

    with transaction.atomic(), pytest.raises(IntegrityError):
        _resource(application=first.application, external_ref="SBXID_1002")


def test_the_same_application_may_hold_one_resource_per_system():
    first = _resource()

    second = _resource(
        application=first.application,
        system=ProvisionedSystem.WSO2,
        external_ref="wso2-app-1",
    )

    assert second.pk != first.pk


def test_a_soft_deleted_resource_frees_the_slot():
    """Deprovisioning (B8) retires a row; re-provisioning must then be possible."""
    first = _resource()
    first.delete()

    replacement = _resource(application=first.application, external_ref="SBXID_1003")

    assert replacement.state == ProvisionedResourceState.ACTIVE
    assert ProvisionedResource.objects.count() == 1
    assert ProvisionedResource.all_objects.count() == LIVE_PLUS_RETIRED


def test_notification_is_not_a_provisionable_system():
    """`ports.ExternalSystem` also has NOTIFICATION — something we send through,
    not something we create a resource in, so the ledger must refuse it."""
    with transaction.atomic(), pytest.raises(IntegrityError):
        _resource(system="NOTIFICATION")


def test_state_must_be_a_known_value():
    with transaction.atomic(), pytest.raises(IntegrityError):
        _resource(state="WOBBLY")


def test_the_application_cannot_be_hard_deleted_from_under_the_ledger():
    """`BaseModel.delete()` is a soft delete, so this is the queryset-level
    delete a cleanup script or the admin would reach for."""
    resource = _resource()
    applications = Application.objects.filter(pk=resource.application_id)

    with transaction.atomic(), pytest.raises(ProtectedError):
        applications.delete()


def test_secret_ref_defaults_to_empty_and_holds_a_reference_only():
    """05-security §3: legacy stored the plaintext secret in
    `sd_status.gen_securate`. Nothing here ever holds a secret value."""
    resource = _resource()

    assert resource.secret_ref == ""
