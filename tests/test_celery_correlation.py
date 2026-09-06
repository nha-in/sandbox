"""The correlation id's ride across the broker.

Neither handler is reachable from an ordinary test: `task_always_eager` calls
tasks inline, so `before_task_publish` never fires and no header exists to bind
from. That is the whole reason these are exercised directly — the path that
matters in production is the one tests never take, and the seven hand-threaded
`correlation_id` arguments this replaced were never covered either.
"""

from __future__ import annotations

from types import SimpleNamespace

from celery.signals import before_task_publish

from config.celery_app import CORRELATION_HEADER
from config.celery_app import attach_correlation_id
from config.celery_app import bind_correlation_id
from sandbox.integrations.tasks import provision_keycloak
from sandbox.notifications.tasks import send_notification
from sandbox.utils.correlation import get_correlation_id
from sandbox.utils.correlation import set_correlation_id

PUBLISHED = "0af7651916cd43dd8448eb211c80319c"
AMBIENT = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _task(**request):
    return SimpleNamespace(request=SimpleNamespace(**request))


def test_publishing_stamps_the_current_id_onto_the_message():
    set_correlation_id(PUBLISHED)
    headers: dict[str, str] = {}

    attach_correlation_id(headers=headers)

    assert headers[CORRELATION_HEADER] == PUBLISHED


def test_the_header_is_not_named_after_celerys_own_correlation_id():
    """`Context.correlation_id` is the task id, and `_get_custom_headers` drops
    every name Celery already owns — so that name would be swallowed."""
    assert CORRELATION_HEADER != "correlation_id"


def test_an_id_already_on_the_message_is_left_alone():
    """A retry republishes; it must not be renamed mid-flight."""
    set_correlation_id(AMBIENT)
    headers = {CORRELATION_HEADER: PUBLISHED}

    attach_correlation_id(headers=headers)

    assert headers[CORRELATION_HEADER] == PUBLISHED


def test_publishing_without_headers_does_not_raise():
    """Not every publish path passes them; the signal must stay harmless."""
    attach_correlation_id(headers=None)


def test_a_task_binds_the_id_its_message_carried():
    """The overwrite that matters: a worker is long-lived, so the ContextVar
    arrives holding whatever the previous task left in it."""
    set_correlation_id(AMBIENT)

    bind_correlation_id(task=_task(**{CORRELATION_HEADER: PUBLISHED}))

    assert get_correlation_id() == PUBLISHED


def test_a_task_with_no_header_keeps_the_ambient_id():
    """Eager mode never published, so the ambient context is already the
    caller's. Clearing it here would break every chain run inline."""
    set_correlation_id(AMBIENT)

    bind_correlation_id(task=_task())

    assert get_correlation_id() == AMBIENT


def test_binding_survives_a_task_with_no_request_at_all():
    set_correlation_id(AMBIENT)

    bind_correlation_id(task=SimpleNamespace())

    assert get_correlation_id() == AMBIENT


def test_a_real_publish_stamps_every_task_including_the_ones_that_never_asked(
    settings,
):
    """The bug this replaced: `send_notification` threaded no correlation id.

    The provisioning chain enqueues it on completion, and it reaches the
    notification gateway through `http.py`, which stamps `X-Correlation-Id`
    from the ContextVar — so it minted a fresh id and the approval email's
    outbound call joined to nothing.

    Published for real against the memory broker rather than run: eager mode
    skips publishing entirely, which is precisely why this went unnoticed.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = False
    stamped: list[str | None] = []

    def spy(headers=None, **_kwargs):
        stamped.append(headers.get(CORRELATION_HEADER) if headers else None)

    before_task_publish.connect(spy)
    set_correlation_id(PUBLISHED)
    try:
        send_notification.apply_async(args=(1,))
        provision_keycloak.apply_async(args=(1,))
    finally:
        before_task_publish.disconnect(spy)

    assert stamped == [PUBLISHED, PUBLISHED]
