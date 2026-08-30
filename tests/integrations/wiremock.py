"""A thin client for WireMock's admin API.

Only what B9 needs: install a stub, read the request journal, wipe both. Kept
here rather than pulling in a WireMock SDK because the admin API is four URLs
and a vendored client would be more code than this.
"""

from __future__ import annotations

from typing import Any

import httpx

#: WireMock's own fault names — a socket-level failure, not an HTTP status.
CONNECTION_RESET = "CONNECTION_RESET_BY_PEER"
EMPTY_RESPONSE = "EMPTY_RESPONSE"


class WireMock:
    """Programs the pretend network for one test, and reads back what it saw."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._admin = httpx.Client(base_url=f"{self.base_url}/__admin", timeout=10.0)

    def close(self) -> None:
        self._admin.close()

    def reset(self) -> None:
        """Drop every stub and every recorded request."""
        self._admin.post("/reset").raise_for_status()

    def stub(  # noqa: PLR0913 - one keyword per WireMock knob; a dict would hide them
        self,
        method: str,
        url_pattern: str,
        *,
        status: int = 200,
        json_body: Any = None,
        body: str | None = None,
        headers: dict[str, str] | None = None,
        delay_ms: int | None = None,
        fault: str | None = None,
        scenario: str | None = None,
        required_state: str | None = None,
        next_state: str | None = None,
        priority: int | None = None,
    ) -> None:
        """Install one stub. `scenario` + states express "fail once, then work"."""
        response: dict[str, Any] = {"status": status}
        if json_body is not None:
            response["jsonBody"] = json_body
        if body is not None:
            response["body"] = body
        if headers:
            response["headers"] = headers
        if delay_ms is not None:
            response["fixedDelayMilliseconds"] = delay_ms
        if fault is not None:
            # A fault replaces the response entirely: WireMock breaks the socket.
            response = {"fault": fault}

        mapping: dict[str, Any] = {
            "request": {"method": method.upper(), "urlPattern": url_pattern},
            "response": response,
        }
        if priority is not None:
            mapping["priority"] = priority
        if scenario is not None:
            mapping["scenarioName"] = scenario
            mapping["requiredScenarioState"] = required_state or "Started"
            if next_state is not None:
                mapping["newScenarioState"] = next_state

        self._admin.post("/mappings", json=mapping).raise_for_status()

    def count(self, method: str, url_pattern: str) -> int:
        """How many matching requests actually reached the wire."""
        response = self._admin.post(
            "/requests/count",
            json={"method": method.upper(), "urlPattern": url_pattern},
        )
        response.raise_for_status()
        return int(response.json()["count"])

    def journal(self) -> list[dict[str, Any]]:
        response = self._admin.get("/requests")
        response.raise_for_status()
        return [entry["request"] for entry in response.json()["requests"]]
