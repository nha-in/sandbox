"""Settings guards that make dangerous environment combinations impossible.

v1's deadliest misconfiguration was a debug-mode process pointed at shared
infrastructure. These guards fail at settings-import time instead.
"""

from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

# Hostnames that can only ever resolve to the developer's own machine or the
# service names inside the local compose network.
LOCAL_HOSTS = frozenset(
    {
        "",
        "localhost",
        "127.0.0.1",
        "::1",
        "host.docker.internal",
        "postgres",
        "redis",
        "mailpit",
        "db",
    },
)


def _is_local(host: str | None) -> bool:
    return (host or "").strip().lower() in LOCAL_HOSTS


def assert_isolated_local_environment(
    debug: bool,  # noqa: FBT001
    databases: dict[str, dict[str, Any]],
    redis_url: str,
) -> None:
    """Refuse to boot a DEBUG process that talks to non-local infrastructure."""
    if not debug:
        return

    offenders = []
    db_host = databases.get("default", {}).get("HOST", "")
    if not _is_local(db_host):
        offenders.append(f"database host {db_host!r}")
    redis_host = urlsplit(redis_url).hostname
    if not _is_local(redis_host):
        offenders.append(f"redis host {redis_host!r}")

    if offenders:
        msg = (
            "DEBUG is enabled but this process is configured against "
            f"non-local infrastructure ({', '.join(offenders)}). "
            "Refusing to start."
        )
        raise ImproperlyConfigured(msg)


def assert_staff_mfa_is_required(
    debug: bool,  # noqa: FBT001
    staff_mfa_required: bool,  # noqa: FBT001
) -> None:
    """The console and the admin are where a stolen password does most damage.

    `STAFF_MFA_REQUIRED` exists only so a developer can click through the
    console without an authenticator app. It has no environment override, so
    turning it off takes an edit to a settings module — and this refuses to boot
    if that module is one where DEBUG is off.
    """
    if staff_mfa_required or debug:
        return

    msg = (
        "STAFF_MFA_REQUIRED is False with DEBUG off. Two-factor authentication "
        "for staff is not optional outside local development. Refusing to start."
    )
    raise ImproperlyConfigured(msg)
