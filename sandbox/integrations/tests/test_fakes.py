"""Fakes must behave like the real thing where it matters, and be resettable."""

from __future__ import annotations

import time
from typing import Any

import pytest
from django.core import mail

from sandbox.integrations import fakes
from sandbox.integrations.fakes import FakeApiGateway
from sandbox.integrations.fakes import FakeBridgeRegistry
from sandbox.integrations.fakes import FakeIdpAdmin
from sandbox.integrations.fakes import FakeNotificationGateway
from sandbox.integrations.ports import AdapterError
from sandbox.integrations.ports import ApiGateway
from sandbox.integrations.ports import BridgeRegistry
from sandbox.integrations.ports import BridgeSpec
from sandbox.integrations.ports import ClientSpec
from sandbox.integrations.ports import ExternalSystem
from sandbox.integrations.ports import GatewayAppSpec
from sandbox.integrations.ports import IdpAdmin
from sandbox.integrations.ports import NotificationGateway
from sandbox.integrations.ports import NotificationMessage
from sandbox.integrations.secret_ref import store_secret

SPEC = ClientSpec(reference="SBX-2026-00001", display_name="Acme", role_names=("hip",))
APP_SPEC = GatewayAppSpec(reference="SBX-2026-00001", name="Acme", api_names=("abha",))
BRIDGE_SPEC = BridgeSpec(bridge_id="SBX_ABC", name="Acme", url="https://acme.test")
# A pointer into a secret store, never a secret value. Deliberately never parked,
# so it stands in for one that has expired.
SECRET_REF = "vault://x"  # noqa: S105
LATENCY = 0.05


@pytest.fixture(autouse=True)
def _no_activation_delay(settings):
    settings.FAKE_BRIDGE_ACTIVATION_DELAY_SECONDS = 0.0


def client_record(idp: FakeIdpAdmin, external_id: str) -> dict[str, Any]:
    record = idp.get_client(external_id)
    assert record is not None
    return record


def app_record(gateway: FakeApiGateway, external_id: str) -> dict[str, Any]:
    record = gateway.get_application(external_id)
    assert record is not None
    return record


def test_fakes_satisfy_their_protocols() -> None:
    """Conformance is structural: mypy fails this file if a fake drifts."""
    idp: IdpAdmin = FakeIdpAdmin()
    gateway: ApiGateway = FakeApiGateway()
    registry: BridgeRegistry = FakeBridgeRegistry()
    notifier: NotificationGateway = FakeNotificationGateway()

    assert isinstance(idp, FakeIdpAdmin)
    assert isinstance(gateway, FakeApiGateway)
    assert isinstance(registry, FakeBridgeRegistry)
    assert isinstance(notifier, FakeNotificationGateway)


# Keycloak


def test_created_client_gets_a_non_derivable_id_and_a_secret():
    first = FakeIdpAdmin().create_client(SPEC)
    second = FakeIdpAdmin().create_client(SPEC)

    assert first.client_id != second.client_id  # never sequence-derived
    assert SPEC.reference not in first.client_id
    assert first.initial_secret
    assert first.initial_secret != second.initial_secret


def test_reading_a_client_never_rotates_its_secret():
    """The legacy system's exact bug: getSecret was bound to POST."""
    idp = FakeIdpAdmin()
    created = idp.create_client(SPEC)

    first = client_record(idp, created.external_id)["secret"]
    second = client_record(idp, created.external_id)["secret"]

    assert first == second == created.initial_secret


def test_rotate_returns_a_new_secret():
    idp = FakeIdpAdmin()
    created = idp.create_client(SPEC)

    rotated = idp.rotate_client_secret(created.external_id)

    assert rotated.secret != created.initial_secret
    assert client_record(idp, created.external_id)["secret"] == rotated.secret


def test_rotating_an_unknown_client_is_a_non_retryable_error():
    with pytest.raises(AdapterError) as excinfo:
        FakeIdpAdmin().rotate_client_secret("nope")

    assert excinfo.value.retryable is False


def test_disable_is_idempotent_even_for_a_missing_client():
    idp = FakeIdpAdmin()
    created = idp.create_client(SPEC)

    idp.disable_client(created.external_id)
    idp.disable_client(created.external_id)
    idp.disable_client("never-existed")  # B8 requires this to succeed

    assert client_record(idp, created.external_id)["enabled"] is False


def test_requested_roles_are_recorded_by_name():
    idp = FakeIdpAdmin()
    created = idp.create_client(ClientSpec("SBX-1", "Acme", ("hip", "hiu")))

    assert client_record(idp, created.external_id)["roles"] == ["hip", "hiu"]


# WSO2


def test_gateway_application_tracks_subscriptions():
    gateway = FakeApiGateway()
    created = gateway.create_application(APP_SPEC)

    gateway.subscribe(created.external_id, ("hip", "hiu"))
    gateway.unsubscribe(created.external_id, ("hip",))

    assert app_record(gateway, created.external_id)["subscriptions"] == ["abha", "hiu"]


def test_unsubscribe_is_idempotent_for_a_missing_application():
    FakeApiGateway().unsubscribe("never-existed", ("abha",))


def test_map_keys_stores_a_reference_not_a_secret():
    gateway = FakeApiGateway()
    created = gateway.create_application(APP_SPEC)
    ref = store_secret("the-actual-secret")

    gateway.map_keys(created.external_id, consumer_key="ck", secret_ref=ref)

    record = app_record(gateway, created.external_id)
    assert record["keys_mapped"] is True
    assert record["secret_ref"] == ref
    assert "the-actual-secret" not in str(record)


def test_map_keys_refuses_a_reference_that_has_expired():
    """The fake has to fail here too, or B7's expiry dead-end is invisible in CI."""
    gateway = FakeApiGateway()
    created = gateway.create_application(APP_SPEC)

    with pytest.raises(AdapterError) as exc:
        gateway.map_keys(
            created.external_id,
            consumer_key="ck",
            secret_ref=SECRET_REF,
        )

    assert exc.value.code == "SECRET_REF_EXPIRED"


# HIE-CM


def test_bridge_becomes_active_after_the_configured_delay(settings):
    settings.FAKE_BRIDGE_ACTIVATION_DELAY_SECONDS = 0.05
    registry = FakeBridgeRegistry()
    registry.create_bridge(BRIDGE_SPEC)

    assert registry.get_bridge_status(BRIDGE_SPEC.bridge_id).active is False

    time.sleep(0.06)

    assert registry.get_bridge_status(BRIDGE_SPEC.bridge_id).active is True


def test_deactivated_bridge_reports_inactive_and_deactivate_is_idempotent():
    registry = FakeBridgeRegistry()
    registry.create_bridge(BRIDGE_SPEC)

    registry.deactivate_bridge(BRIDGE_SPEC.bridge_id)
    registry.deactivate_bridge(BRIDGE_SPEC.bridge_id)
    registry.deactivate_bridge("never-existed")

    assert registry.get_bridge_status(BRIDGE_SPEC.bridge_id).active is False


def test_status_of_an_unknown_bridge_is_a_non_retryable_error():
    with pytest.raises(AdapterError) as excinfo:
        FakeBridgeRegistry().get_bridge_status("nope")

    assert excinfo.value.retryable is False


# Notification


def test_notification_goes_through_the_email_backend():
    """Locally this is Mailpit; under test it is locmem, hence the outbox."""
    result = FakeNotificationGateway().send(
        NotificationMessage(
            template="sandbox-approved",
            to="a@b.test",
            context={"ref": "SBX-1"},
        ),
    )

    assert result.accepted is True
    assert result.provider_message_id
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["a@b.test"]
    assert "sandbox-approved" in mail.outbox[0].subject
    assert "ref: SBX-1" in mail.outbox[0].body


def test_sends_are_recorded_for_assertions():
    notifier = FakeNotificationGateway()
    notifier.send(NotificationMessage(template="send-otp", to="a@b.test", context={}))

    assert [send["template"] for send in fakes.recorded_sends()] == ["send-otp"]


# Failure injection


def test_fail_next_fires_once_then_clears():
    fakes.fail_next(ExternalSystem.KEYCLOAK, "create_client")
    idp = FakeIdpAdmin()

    with pytest.raises(AdapterError) as excinfo:
        idp.create_client(SPEC)
    assert excinfo.value.code == "FAKE_FAILURE"

    assert idp.create_client(SPEC).client_id  # second call succeeds


def test_fail_next_is_scoped_to_one_operation():
    fakes.fail_next(ExternalSystem.KEYCLOAK, "rotate_client_secret")

    created = FakeIdpAdmin().create_client(SPEC)  # different op, unaffected

    with pytest.raises(AdapterError):
        FakeIdpAdmin().rotate_client_secret(created.external_id)


def test_always_fail_persists_until_cleared():
    fakes.always_fail(ExternalSystem.WSO2, code="FAKE_DOWN", retryable=True)
    gateway = FakeApiGateway()

    for _ in range(3):
        with pytest.raises(AdapterError) as excinfo:
            gateway.create_application(APP_SPEC)
        assert excinfo.value.code == "FAKE_DOWN"

    fakes.clear_failures(ExternalSystem.WSO2)

    assert gateway.create_application(APP_SPEC).name == "Acme"


def test_failure_injection_is_scoped_to_one_system():
    fakes.always_fail(ExternalSystem.WSO2)

    assert FakeIdpAdmin().create_client(SPEC).client_id  # Keycloak unaffected


def test_injected_failures_are_adapter_errors_with_a_retryable_flag():
    fakes.always_fail(ExternalSystem.HIECM, code="FAKE_4XX", retryable=False)

    with pytest.raises(AdapterError) as excinfo:
        FakeBridgeRegistry().create_bridge(BRIDGE_SPEC)

    assert excinfo.value.system is ExternalSystem.HIECM
    assert excinfo.value.retryable is False


def test_latency_injection_delays_the_call():
    fakes.set_latency(ExternalSystem.KEYCLOAK, LATENCY)

    started = time.monotonic()
    FakeIdpAdmin().create_client(SPEC)

    assert time.monotonic() - started >= LATENCY


# Reset


def test_reset_clears_state_and_failure_knobs():
    idp = FakeIdpAdmin()
    created = idp.create_client(SPEC)
    fakes.always_fail(ExternalSystem.WSO2)

    fakes.reset_fakes()

    assert idp.get_client(created.external_id) is None
    assert FakeApiGateway().create_application(APP_SPEC).name == "Acme"
    assert fakes.recorded_sends() == []
