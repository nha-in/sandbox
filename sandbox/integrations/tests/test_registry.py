"""The settings toggle that lets a port resolve to a real adapter or a fake."""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from sandbox.integrations import registry
from sandbox.integrations.ports import ClientCreated
from sandbox.integrations.ports import ClientSpec
from sandbox.integrations.ports import SecretRotated


class StubIdpAdmin:
    def create_client(self, spec: ClientSpec) -> ClientCreated:
        return ClientCreated(
            client_id=spec.reference,
            external_id="uuid",
            initial_secret="s",  # noqa: S106
        )

    def rotate_client_secret(self, external_id: str) -> SecretRotated:
        return SecretRotated(external_id=external_id, secret="s")  # noqa: S106

    def disable_client(self, external_id: str) -> None:
        return None


STUB = "sandbox.integrations.tests.test_registry.StubIdpAdmin"


def test_port_resolves_to_the_configured_adapter(settings):
    settings.INTEGRATION_PORTS = {"IDP": STUB}

    assert isinstance(registry.get_idp_admin(), StubIdpAdmin)


def test_unconfigured_port_fails_loudly(settings):
    settings.INTEGRATION_PORTS = {}

    with pytest.raises(ImproperlyConfigured, match="No adapter configured"):
        registry.get_idp_admin()


def test_unimportable_adapter_fails_loudly(settings):
    settings.INTEGRATION_PORTS = {"IDP": "sandbox.integrations.nope.Missing"}

    with pytest.raises(ImproperlyConfigured, match="could not be imported"):
        registry.get_idp_admin()


@pytest.mark.parametrize(
    ("accessor", "port"),
    [
        (registry.get_idp_admin, "IDP"),
        (registry.get_api_gateway, "API_GATEWAY"),
        (registry.get_bridge_registry, "BRIDGE_REGISTRY"),
        (registry.get_notification_gateway, "NOTIFICATION"),
    ],
)
def test_every_port_has_an_accessor(settings, accessor, port):
    settings.INTEGRATION_PORTS = {port: STUB}

    assert isinstance(accessor(), StubIdpAdmin)
