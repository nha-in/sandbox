"""A stand-in ABDM notification service.

Records every request so the tests can assert the wire shape legacy's
`NotificationRequestDTO` describes, and can force failures to exercise the
timeout, breaker and no-retry-on-POST rules.
"""

from __future__ import annotations

import json

import httpx

MESSAGE_PATH = "/internal/v3/notification/message"

OK = 200
NOT_FOUND = 404


class NotificationStubTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.status = OK
        self.body: dict | None = {"status": "SENT", "messageId": "prv-1"}
        self.raw_body: str | None = None
        self.timeout = False

    def bodies(self) -> list[dict]:
        return [json.loads(call.content) for call in self.calls]

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)

        if self.timeout:
            message = "read timed out"
            raise httpx.ReadTimeout(message, request=request)

        if request.url.path != MESSAGE_PATH or request.method != "POST":
            return httpx.Response(NOT_FOUND, json={"error": "unstubbed"})

        if self.raw_body is not None:
            return httpx.Response(self.status, content=self.raw_body)
        return httpx.Response(self.status, json=self.body)
