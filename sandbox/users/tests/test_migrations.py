"""The one migration whose bug an empty database cannot show.

`AddField(external_id, default=uuid.uuid4, unique=True)` evaluates its default
once and writes that single UUID to every existing row, so the unique index
fails to build. CI migrates an empty database and stays green; staging breaks
mid-deploy. The fix (add nullable → backfill → constrain) is only meaningful
against rows that already exist, which is what this exercises.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

APP = "users"
BEFORE = [(APP, "0001_initial")]
AFTER = [(APP, "0002_user_email_verified_at_user_external_id_user_phone_and_more")]

EXISTING_USERS = 2


def _migrate(targets: list[tuple[str, str]]):
    """Run the plan and hand back the historical models at that point."""
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor.loader.project_state(targets).apps


def test_the_backfill_gives_every_pre_existing_row_its_own_external_id():
    old_apps = _migrate(BEFORE)
    try:
        user_model = old_apps.get_model(APP, "User")
        for index in range(EXISTING_USERS):
            user_model.objects.create(email=f"existing-{index}@example.com")

        new_apps = _migrate(AFTER)
        external_ids = list(
            new_apps.get_model(APP, "User")
            .objects.order_by("id")
            .values_list("external_id", flat=True),
        )
    finally:
        # Later tests in this session share the schema, so end where we started.
        _migrate(AFTER)

    assert len(external_ids) == EXISTING_USERS
    assert all(external_ids), "a pre-existing row was left without an external_id"
    assert len(set(external_ids)) == EXISTING_USERS, (
        "every row got the same UUID — the default was evaluated once, so the "
        "unique index would fail to build on any real database"
    )
