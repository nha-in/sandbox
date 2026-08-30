"""B1's HTTP policy, observed over a real socket rather than asserted about.

Every claim here is one the `*_stub.py` transports cannot make. They replace
httpx's transport, so a "timeout" test there raises `httpx.ReadTimeout` by hand:
it proves the `except` clause works, not that `HttpPolicy.read_timeout` was ever
wired to anything. Here the response really is slow, the socket really does
break, and the request journal is WireMock's rather than our own bookkeeping.
"""

from __future__ import annotations

import time

import pytest
from django.test import override_settings

from sandbox.integrations.http import HttpPolicy
from sandbox.integrations.http import IntegrationClient
from sandbox.integrations.notification.adapter import AbdmNotificationGateway
from sandbox.integrations.ports import AdapterError
from sandbox.integrations.ports import ExternalSystem
from sandbox.integrations.ports import NotificationMessage
from tests.integrations.wiremock import CONNECTION_RESET

READ_TIMEOUT = 0.5
MAX_ATTEMPTS = 3
BREAKER_FAIL_MAX = 5
SERVER_ERROR = 500
BAD_REQUEST = 400
#: comfortably longer than READ_TIMEOUT, comfortably shorter than the test suite
SLOW_MS = 2000
PATH = "/probe"
#: one 0.4s attempt plus overhead, nowhere near SLOW_MS
TIMEOUT_BUDGET = 1.5
RETRY_THEN_SUCCEED = 2


@pytest.fixture
def client(wiremock_url):
    policy = HttpPolicy(
        system=ExternalSystem.KEYCLOAK,
        base_url=wiremock_url,
        read_timeout=READ_TIMEOUT,
        max_attempts=MAX_ATTEMPTS,
        backoff_initial=0.01,
        backoff_max=0.05,
        breaker_fail_max=BREAKER_FAIL_MAX,
    )
    built = IntegrationClient(policy)
    yield built
    built.close()


# Timeouts


def test_a_slow_response_times_out_within_the_configured_budget(wiremock, client):
    """The claim a transport stub cannot make: the budget is real and enforced."""
    wiremock.stub("GET", PATH, delay_ms=SLOW_MS, json_body={"ok": True})

    started = time.monotonic()
    with pytest.raises(AdapterError) as exc:
        client.request("GET", PATH, op="probe")
    elapsed = time.monotonic() - started

    assert exc.value.code == "TIMEOUT"
    assert exc.value.retryable is True
    # Three attempts, each bounded by the read timeout, plus a little backoff —
    # and nowhere near the two seconds WireMock was told to wait.
    assert elapsed < READ_TIMEOUT * MAX_ATTEMPTS + 1.0


def test_a_timeout_does_not_hang_the_caller(wiremock, client):
    wiremock.stub("GET", PATH, delay_ms=SLOW_MS)

    with pytest.raises(AdapterError):
        client.request("GET", PATH, op="probe")

    assert wiremock.count("GET", PATH) == MAX_ATTEMPTS


# Retries


def test_an_idempotent_call_is_retried_exactly_to_the_limit(wiremock, client):
    wiremock.stub("GET", PATH, status=SERVER_ERROR, json_body={"error": "boom"})

    with pytest.raises(AdapterError) as exc:
        client.request("GET", PATH, op="probe")

    assert exc.value.code == f"HTTP_{SERVER_ERROR}"
    assert wiremock.count("GET", PATH) == MAX_ATTEMPTS


def test_a_non_idempotent_post_is_never_retried(wiremock, client):
    """A retried POST is a second side effect; the journal is the proof."""
    wiremock.stub("POST", PATH, status=SERVER_ERROR, json_body={"error": "boom"})

    with pytest.raises(AdapterError):
        client.request("POST", PATH, op="probe")

    assert wiremock.count("POST", PATH) == 1


def test_a_client_error_is_not_retried(wiremock, client):
    """A 4xx is our bug. Repeating it three times just triples the noise."""
    wiremock.stub("GET", PATH, status=BAD_REQUEST, json_body={"error": "nope"})

    with pytest.raises(AdapterError) as exc:
        client.request("GET", PATH, op="probe")

    assert exc.value.retryable is False
    assert wiremock.count("GET", PATH) == 1


def test_a_retry_can_succeed(wiremock, client):
    """Scenario states: fail once, then answer."""
    wiremock.stub(
        "GET",
        PATH,
        status=SERVER_ERROR,
        scenario="flaky",
        required_state="Started",
        next_state="recovered",
    )
    wiremock.stub(
        "GET",
        PATH,
        json_body={"ok": True},
        scenario="flaky",
        required_state="recovered",
    )

    response = client.request("GET", PATH, op="probe")

    assert response.json() == {"ok": True}
    assert wiremock.count("GET", PATH) == RETRY_THEN_SUCCEED


# Breaker


def test_the_breaker_opens_and_then_stops_touching_the_network(wiremock, client):
    wiremock.stub("GET", PATH, status=SERVER_ERROR)

    for _ in range(BREAKER_FAIL_MAX):
        with pytest.raises(AdapterError):
            client.request("GET", PATH, op="probe", idempotent=False)

    with pytest.raises(AdapterError) as exc:
        client.request("GET", PATH, op="probe", idempotent=False)

    assert exc.value.code == "CIRCUIT_OPEN"
    # The point of a breaker: the last call never left the process.
    assert wiremock.count("GET", PATH) == BREAKER_FAIL_MAX


def test_client_errors_do_not_open_the_breaker(wiremock, client):
    wiremock.stub("GET", PATH, status=BAD_REQUEST)

    for _ in range(BREAKER_FAIL_MAX + 2):
        with pytest.raises(AdapterError) as exc:
            client.request("GET", PATH, op="probe")
        assert exc.value.code == f"HTTP_{BAD_REQUEST}"

    assert wiremock.count("GET", PATH) == BREAKER_FAIL_MAX + 2


def test_the_breaker_lets_a_probe_through_once_it_resets(wiremock, wiremock_url):
    """Half-open: after the reset window one call is allowed to test the water."""
    policy = HttpPolicy(
        system=ExternalSystem.WSO2,
        base_url=wiremock_url,
        read_timeout=READ_TIMEOUT,
        max_attempts=1,
        breaker_fail_max=2,
        breaker_reset_timeout=0.2,
    )
    with IntegrationClient(policy) as client:
        wiremock.stub("GET", PATH, status=SERVER_ERROR, scenario="down")
        for _ in range(2):
            with pytest.raises(AdapterError):
                client.request("GET", PATH, op="probe")
        with pytest.raises(AdapterError) as exc:
            client.request("GET", PATH, op="probe")
        assert exc.value.code == "CIRCUIT_OPEN"

        time.sleep(0.3)
        wiremock.reset()
        wiremock.stub("GET", PATH, json_body={"ok": True})

        assert client.request("GET", PATH, op="probe").json() == {"ok": True}


# Broken sockets and broken bodies


def test_a_severed_connection_becomes_a_typed_adapter_error(wiremock, client):
    """No httpx exception may escape an adapter, including transport-level ones."""
    wiremock.stub("GET", PATH, fault=CONNECTION_RESET)

    with pytest.raises(AdapterError) as exc:
        client.request("GET", PATH, op="probe")

    assert exc.value.code == "TRANSPORT_ERROR"
    assert exc.value.retryable is True


def test_a_body_that_is_not_json_becomes_a_typed_adapter_error(wiremock, wiremock_url):
    """Adapters own their parsing; a 200 full of HTML must not raise ValueError."""
    wiremock.stub(
        "POST",
        "/internal/v3/notification/message",
        body="<html>gateway is unwell</html>",
        headers={"Content-Type": "text/html"},
    )

    with override_settings(
        NOTIFICATION_BASE_URL=wiremock_url,
        NOTIFICATION_TEMPLATE_IDS={"production-approved": "106"},
    ):
        gateway = AbdmNotificationGateway()
        with pytest.raises(AdapterError) as exc:
            gateway.send(
                NotificationMessage(
                    template="production-approved",
                    to="dev@example.test",
                    context={
                        "applicant": "Asha",
                        "reference": "SBX-2026-00001",
                        "product": "Demo HMIS",
                    },
                ),
            )
        gateway._client.close()  # noqa: SLF001

    assert exc.value.code == "MALFORMED_RESPONSE"
    assert exc.value.retryable is False


def test_the_notification_read_timeout_is_the_configured_five_seconds(
    wiremock,
    wiremock_url,
):
    """Per-adapter budgets are settings, so they are worth observing once."""
    with override_settings(
        NOTIFICATION_BASE_URL=wiremock_url,
        NOTIFICATION_READ_TIMEOUT_SECONDS=0.4,
        NOTIFICATION_TEMPLATE_IDS={"production-approved": "106"},
    ):
        wiremock.stub(
            "POST",
            "/internal/v3/notification/message",
            delay_ms=SLOW_MS,
        )
        gateway = AbdmNotificationGateway()
        started = time.monotonic()
        with pytest.raises(AdapterError) as exc:
            gateway.send(
                NotificationMessage(
                    template="production-approved",
                    to="dev@example.test",
                    context={
                        "applicant": "Asha",
                        "reference": "SBX-2026-00001",
                        "product": "Demo HMIS",
                    },
                ),
            )
        elapsed = time.monotonic() - started
        gateway._client.close()  # noqa: SLF001

    assert exc.value.code == "TIMEOUT"
    # One attempt only: send is a POST, and a resent POST is a second email.
    assert elapsed < TIMEOUT_BUDGET
    assert wiremock.count("POST", "/internal/v3/notification/message") == 1
