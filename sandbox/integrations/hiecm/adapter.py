"""HIE-CM bridge registry — the third and last thing provisioning creates.

A bridge is ABDM's record that *this* integrator's system may exchange health
data, at *these* endpoints. Without it a valid token and a live subscription
still move nothing.

What legacy did here, all verified in source:

Bridge ids were the Keycloak client id — `bridge.setBridgeId(integratorClientId)`
in `WorkflowServiceImpl.addEntryToBridgeTable`, and those ids were derived as
`SBXID_(sdId + 55)`. So a bridge id was both guessable and publicly visible.
B3's client ids are random, and this adapter takes whatever id it is given
rather than deriving one.

Every bridge was registered pointing at the same hardcoded `webhook.site` URL
(`SandboxConstant.BRIDGE_CALLBACK_URL`), not the integrator's own endpoint.

Bridges were never deactivated. `HIECMGatewayFClient` declares exactly three
calls — find, add, update-url — and the rejection path only deletes the
Keycloak client, so a rejected integrator's bridge outlived the rejection.
`deactivate_bridge` is the missing fourth, expressed as the PATCH the update
endpoint already supports.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Any
from typing import NoReturn
from urllib.parse import quote

from django.conf import settings

from sandbox.integrations.http import HttpPolicy
from sandbox.integrations.http import IntegrationClient
from sandbox.integrations.http import Token
from sandbox.integrations.http import TokenCache
from sandbox.integrations.ports import AdapterError
from sandbox.integrations.ports import BridgeCreated
from sandbox.integrations.ports import BridgeStatus
from sandbox.integrations.ports import ExternalSystem

if TYPE_CHECKING:
    import httpx

    from sandbox.integrations.ports import BridgeSpec

NOT_FOUND = "HTTP_404"

#: ABDM gateway convention; `X-CM-ID` is the only one legacy spelled out
#: (SandboxConstant.X_CM_ID), the other two come from its shared ABDMConstant.
REQUEST_ID_HEADER = "REQUEST-ID"
TIMESTAMP_HEADER = "TIMESTAMP"
CM_ID_HEADER = "X-CM-ID"

#: GeneralUtils.TIMESTAMP_FORMAT — milliseconds, UTC, trailing Z.
_TIMESTAMP_PRECISION = "milliseconds"


class HiecmBridgeRegistry:
    """Implements `BridgeRegistry` over the HIE-CM gateway API."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._api = settings.HIECM_API_PATH.rstrip("/")
        policy = HttpPolicy(
            system=ExternalSystem.HIECM,
            base_url=settings.HIECM_BASE_URL.rstrip("/"),
        )
        self._auth = IntegrationClient(policy, transport=transport)
        self._client = IntegrationClient(
            policy,
            transport=transport,
            token_cache=TokenCache(self._fetch_token),
        )

    # Lifecycle

    def create_bridge(self, spec: BridgeSpec) -> BridgeCreated:
        """Registration is a PUT, so a re-run overwrites rather than duplicates."""
        self._client.request(
            "PUT",
            f"{self._api}/gateway/bridge",
            op="create_bridge",
            headers=self._gateway_headers(),
            json={
                "bridgeId": spec.bridge_id,
                "name": spec.name,
                "url": spec.url,
                "active": True,
                "blocklisted": False,
            },
        )
        return BridgeCreated(bridge_id=spec.bridge_id)

    def get_bridge_status(self, bridge_id: str) -> BridgeStatus:
        response = self._client.request(
            "GET",
            f"{self._api}/gateway/v3/bridge-services/{_segment(bridge_id)}",
            op="get_bridge_status",
            headers=self._gateway_headers(),
        )
        payload = self._json(response, "get_bridge_status")
        bridge = payload.get("bridge")
        if not isinstance(bridge, dict):
            self._malformed("get_bridge_status", "response had no bridge object")

        # Blocklisted folds into `active`: a blocklisted bridge moves no data, and
        # reporting it as active would tell C7's panel the integrator is ready.
        active = bool(bridge.get("active")) and not bool(bridge.get("blocklisted"))
        return BridgeStatus(bridge_id=bridge_id, active=active)

    def deactivate_bridge(self, bridge_id: str) -> None:
        """Idempotent: an already-inactive or absent bridge is success (B8)."""
        try:
            self._client.request(
                "PATCH",
                f"{self._api}/gateway/bridge",
                op="deactivate_bridge",
                headers=self._gateway_headers(),
                json={"id": bridge_id, "bridgeId": bridge_id, "active": False},
            )
        except AdapterError as error:
            if error.code != NOT_FOUND:
                raise

    # Internals

    def _fetch_token(self) -> Token:
        response = self._auth.request(
            "POST",
            f"{self._api}{settings.HIECM_SESSION_PATH}",
            op="fetch_token",
            # Retry-safe despite being a POST: a session mints nothing durable.
            idempotent=True,
            headers=self._gateway_headers(),
            json={
                "clientId": settings.HIECM_CLIENT_ID,
                "clientSecret": settings.HIECM_CLIENT_SECRET,
            },
        )
        payload = self._json(response, "fetch_token")
        return Token(
            value=self._require(payload, "accessToken", "fetch_token"),
            expires_at=time.monotonic() + float(payload.get("expiresIn", 60)),
        )

    @staticmethod
    def _gateway_headers() -> dict[str, str]:
        return {
            REQUEST_ID_HEADER: str(uuid.uuid4()),
            TIMESTAMP_HEADER: datetime.now(UTC)
            .isoformat(timespec=_TIMESTAMP_PRECISION)
            .replace("+00:00", "Z"),
            CM_ID_HEADER: settings.HIECM_CM_ID,
        }

    def _json(self, response: httpx.Response, op: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            self._malformed(op, "response body was not JSON", cause=exc)
        if not isinstance(payload, dict):
            self._malformed(op, "expected a JSON object")
        return payload

    def _require(self, payload: dict[str, Any], key: str, op: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            self._malformed(op, f"response had no usable {key!r}")
        return value

    def _malformed(
        self,
        op: str,
        detail: str,
        *,
        cause: Exception | None = None,
    ) -> NoReturn:
        raise AdapterError(
            ExternalSystem.HIECM,
            "MALFORMED_RESPONSE",
            retryable=False,
            message=f"{op}: {detail}",
        ) from cause

    def close(self) -> None:
        self._client.close()
        self._auth.close()


def _segment(value: str) -> str:
    """Nothing interpolated into a path may introduce another one."""
    return quote(value, safe="")
