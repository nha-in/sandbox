"""Which gateway APIs each workflow subscribes to.

Names, never ids — legacy configured `wso2.v3-subscription-api-list` as a
comma-separated list of `apiId` UUIDs, so the config was pinned to one WSO2
deployment and nobody could tell from reading it what was being subscribed to.
`Wso2ApiGateway` resolves names to ids at call time.

There is no default: NHA has not published the sandbox API names, and guessing
would either subscribe to nothing or to the wrong thing, both silently.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def api_names_for(kind: str) -> tuple[str, ...]:
    names = tuple(settings.WSO2_API_NAMES.get(kind, ()))
    if not names:
        msg = (
            f"No WSO2 API subscription set configured for workflow "
            f"{kind!r}. Set settings.WSO2_API_NAMES[{kind!r}] (or the "
            f"WSO2_SANDBOX_API_NAMES env var) to the published API names."
        )
        raise ImproperlyConfigured(msg)
    return names
