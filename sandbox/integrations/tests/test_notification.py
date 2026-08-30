"""B6 acceptance criteria — the real gateway adapter."""

from __future__ import annotations

import pytest
from django.test import override_settings

from sandbox.integrations.http import reset_breakers
from sandbox.integrations.notification.adapter import REQUEST_ID_HEADER
from sandbox.integrations.notification.adapter import TIMESTAMP_HEADER
from sandbox.integrations.notification.adapter import AbdmNotificationGateway
from sandbox.integrations.ports import AdapterError
from sandbox.integrations.ports import ExternalSystem
from sandbox.integrations.ports import NotificationChannel
from sandbox.integrations.ports import NotificationMessage
from sandbox.integrations.registry import get_notification_gateway
from sandbox.integrations.tests.notification_stub import MESSAGE_PATH
from sandbox.integrations.tests.notification_stub import NotificationStubTransport

SERVER_ERROR = 500
BAD_REQUEST = 400
BREAKER_FAIL_MAX = 5
READ_TIMEOUT = 5.0

TEMPLATE_IDS = {
    "send-otp": "101",
    "sandbox-approved": "102",
    "sandbox-rejected": "103",
    "exit-sent-back": "104",
    "exit-rejected": "105",
    "production-approved": "106",
}

#: every v0 template with a params set that renders it completely
TEMPLATE_PARAMS = {
    "send-otp": {"code": "123456"},
    "sandbox-approved": {
        "applicant": "Asha",
        "reference": "SBX-2026-00001",
        "product": "Demo HMIS",
        "panel_url": "https://portal.test/applications/x/review/",
    },
    "sandbox-rejected": {
        "applicant": "Asha",
        "reference": "SBX-2026-00001",
        "product": "Demo HMIS",
        "comment": "Callback unreachable.",
    },
    "exit-sent-back": {
        "applicant": "Asha",
        "reference": "SBX-2026-00001",
        "product": "Demo HMIS",
        "comment": "Add the M2 evidence.",
    },
    "exit-rejected": {
        "applicant": "Asha",
        "reference": "SBX-2026-00001",
        "product": "Demo HMIS",
        "comment": "Not ready.",
    },
    "production-approved": {
        "applicant": "Asha",
        "reference": "SBX-2026-00001",
        "product": "Demo HMIS",
    },
}

notification_settings = override_settings(
    NOTIFICATION_BASE_URL="https://notify.test",
    NOTIFICATION_MESSAGE_PATH=MESSAGE_PATH,
    NOTIFICATION_TEMPLATE_IDS=TEMPLATE_IDS,
    NOTIFICATION_ORIGIN="sandbox",
    NOTIFICATION_SENDER="ABDM Sandbox",
)


@pytest.fixture(autouse=True)
def _isolated():
    reset_breakers()
    with notification_settings:
        yield
    reset_breakers()


@pytest.fixture
def transport():
    return NotificationStubTransport()


@pytest.fixture
def gateway(transport):
    built = AbdmNotificationGateway(transport=transport)
    yield built
    built._client.close()  # noqa: SLF001


def _message(template: str = "production-approved", **overrides) -> NotificationMessage:
    return NotificationMessage(
        template=template,
        to="dev@example.test",
        context=TEMPLATE_PARAMS[template],
        **overrides,
    )


# Wire shape


def test_send_posts_the_legacy_notification_shape(gateway, transport):
    gateway.send(_message())

    body = transport.bodies()[0]
    assert body["origin"] == "sandbox"
    assert body["type"] == ["email"]
    assert body["contentType"] == "info"
    assert body["receiver"] == [{"key": "email", "value": "dev@example.test"}]
    keyed = {item["key"]: item["value"] for item in body["notification"]}
    assert keyed["templateId"] == "106"
    assert keyed["subject"]
    assert "SBX-2026-00001" in keyed["content"]


def test_otp_is_flagged_as_otp_content(gateway, transport):
    """The provider shapes otp traffic differently — `NotificationContentType`."""
    gateway.send(_message("send-otp"))

    assert transport.bodies()[0]["contentType"] == "otp"


def test_sms_addresses_a_mobile_not_an_email(gateway, transport):
    gateway.send(_message(channel=NotificationChannel.SMS))

    body = transport.bodies()[0]
    assert body["type"] == ["sms"]
    assert body["receiver"][0]["key"] == "mobile"


def test_every_call_carries_the_gateway_headers(gateway, transport):
    gateway.send(_message())

    headers = transport.calls[0].headers
    assert headers[REQUEST_ID_HEADER]
    assert headers[TIMESTAMP_HEADER].endswith("Z")


@pytest.mark.parametrize("template", sorted(TEMPLATE_PARAMS))
def test_every_v0_template_renders_without_a_gap(gateway, transport, template):
    gateway.send(_message(template))

    keyed = {
        item["key"]: item["value"] for item in transport.bodies()[0]["notification"]
    }
    assert keyed["templateId"] == TEMPLATE_IDS[template]
    assert keyed["content"]
    # An unresolved variable renders empty, so a stray marker means a typo.
    assert "{{" not in keyed["content"]
    for value in TEMPLATE_PARAMS[template].values():
        assert str(value) in keyed["content"]


def test_the_approval_body_links_and_never_carries_a_credential(gateway, transport):
    gateway.send(_message("sandbox-approved"))

    keyed = {
        item["key"]: item["value"] for item in transport.bodies()[0]["notification"]
    }
    assert "https://portal.test/applications/x/review/" in keyed["content"]
    assert "secret" not in keyed["content"].lower()


# Results and failures


def test_a_status_the_gateway_does_not_recognise_is_not_accepted(gateway, transport):
    transport.body = {"status": "QUEUE_FULL"}

    assert gateway.send(_message()).accepted is False


def test_an_accepted_send_carries_the_provider_id(gateway):
    result = gateway.send(_message())

    assert result.accepted is True
    assert result.provider_message_id == "prv-1"


def test_an_empty_body_still_counts_as_accepted(gateway, transport):
    """`NotificationResponseDTO` has one optional field; silence is not failure."""
    transport.body = None
    transport.raw_body = ""

    assert gateway.send(_message()).accepted is True


def test_a_non_json_body_becomes_an_adapter_error(gateway, transport):
    transport.raw_body = "<html>gateway down</html>"

    with pytest.raises(AdapterError) as exc:
        gateway.send(_message())

    assert exc.value.code == "MALFORMED_RESPONSE"
    assert exc.value.retryable is False


def test_an_unmapped_template_fails_before_the_call(gateway, transport):
    with (
        override_settings(NOTIFICATION_TEMPLATE_IDS={}),
        pytest.raises(AdapterError) as exc,
    ):
        gateway.send(_message())

    assert exc.value.code == "UNKNOWN_TEMPLATE"
    assert exc.value.retryable is False
    assert transport.calls == []


def test_a_send_is_never_retried_on_the_wire(gateway, transport):
    """A retried POST is a second email; the Celery task owns retry instead."""
    transport.status = SERVER_ERROR

    with pytest.raises(AdapterError) as exc:
        gateway.send(_message())

    assert exc.value.code == "HTTP_500"
    assert exc.value.retryable is True
    assert len(transport.calls) == 1


def test_a_timeout_is_reported_as_a_retryable_adapter_error(gateway, transport):
    transport.timeout = True

    with pytest.raises(AdapterError) as exc:
        gateway.send(_message())

    assert exc.value.code == "TIMEOUT"
    assert exc.value.retryable is True


def test_the_read_timeout_comes_from_settings(transport):
    with override_settings(NOTIFICATION_READ_TIMEOUT_SECONDS=READ_TIMEOUT):
        built = AbdmNotificationGateway(transport=transport)
        assert built._client._policy.read_timeout == READ_TIMEOUT  # noqa: SLF001
        built._client.close()  # noqa: SLF001


def test_repeated_failures_open_the_breaker(gateway, transport):
    transport.status = SERVER_ERROR
    for _ in range(BREAKER_FAIL_MAX):
        with pytest.raises(AdapterError):
            gateway.send(_message())

    with pytest.raises(AdapterError) as exc:
        gateway.send(_message())

    assert exc.value.code == "CIRCUIT_OPEN"
    assert len(transport.calls) == BREAKER_FAIL_MAX


def test_a_client_error_stays_off_the_breaker(gateway, transport):
    """A 400 is our bug, not the gateway falling over."""
    transport.status = BAD_REQUEST
    for _ in range(BREAKER_FAIL_MAX + 1):
        with pytest.raises(AdapterError) as exc:
            gateway.send(_message())
        assert exc.value.code == f"HTTP_{BAD_REQUEST}"

    assert len(transport.calls) == BREAKER_FAIL_MAX + 1


# Wiring


def test_the_registry_resolves_the_real_adapter():
    with override_settings(
        INTEGRATION_PORTS={
            "NOTIFICATION": (
                "sandbox.integrations.notification.adapter.AbdmNotificationGateway"
            ),
        },
    ):
        assert isinstance(get_notification_gateway(), AbdmNotificationGateway)


def test_errors_are_attributed_to_the_notification_system(gateway, transport):
    transport.status = SERVER_ERROR

    with pytest.raises(AdapterError) as exc:
        gateway.send(_message())

    assert exc.value.system is ExternalSystem.NOTIFICATION
