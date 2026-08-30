"""Harness for the suite that runs the real adapters over a real socket.

The `*_stub.py` transports elsewhere replace httpx's transport, so they can prove
we *handle* a timeout but never that one is *configured*: no socket is ever slow.
These tests point the adapters at WireMock instead, so the timeouts, retry
counts and breaker thresholds in B1's `HttpPolicy` are observed rather than
asserted about.

WireMock is compose-profiled, so it is absent by default and this suite skips.
CI sets `WIREMOCK_REQUIRED=1`, which turns that skip into a failure — otherwise
"nobody started the container" and "everything passes" look identical.
"""

from __future__ import annotations

import os

import httpx
import pytest

from sandbox.integrations.http import reset_breakers
from tests.integrations.wiremock import WireMock

DEFAULT_URL = "http://localhost:8081"


def _wiremock_url() -> str:
    return os.environ.get("WIREMOCK_URL", DEFAULT_URL)


def _reachable(url: str) -> bool:
    try:
        response = httpx.get(f"{url}/__admin/health", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code == httpx.codes.OK


@pytest.fixture(scope="session")
def wiremock_url() -> str:
    url = _wiremock_url()
    if _reachable(url):
        return url

    message = (
        f"WireMock is not answering at {url}. Start it with `docker compose "
        "-f docker-compose.local.yml --profile wiremock up -d wiremock`."
    )
    if os.environ.get("WIREMOCK_REQUIRED"):
        pytest.fail(message)
    pytest.skip(message)
    return url  # pragma: no cover - pytest.skip raises


@pytest.fixture
def wiremock(wiremock_url: str):
    """A clean pretend network per test, and a clean breaker to go with it.

    Breakers are process-global and keyed by system, so a test that deliberately
    opens one would otherwise decide the outcome of the next.
    """
    client = WireMock(wiremock_url)
    client.reset()
    reset_breakers()
    yield client
    client.reset()
    reset_breakers()
    client.close()
