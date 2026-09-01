"""Append-only enforcement, and the deployment condition it depends on.

The migrations revoke UPDATE/DELETE from the connecting role. PostgreSQL skips
every privilege check for a superuser, so that revoke only bites when the
application's database role is **not** a superuser — which is a deployment
requirement, not something the migration can guarantee (07-infra-cicd.md).

These tests therefore prove two separate things: that the shipped SQL revokes
what we claim, and that a non-superuser role really is blocked by it.
"""

from __future__ import annotations

import contextlib
from importlib import import_module

import pytest
from django.db import connection
from django.db import transaction
from django.db.utils import ProgrammingError

from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.users.tests.factories import UserFactory
from sandbox.workflow.engine import transition

pytestmark = pytest.mark.django_db

PROBE_ROLE = "sandbox_append_only_probe"
APPEND_ONLY_TABLES = ("workflow_workflowtransition", "audit_auditevent")


def test_migrations_revoke_write_privileges_on_both_tables():
    workflow_sql = import_module("sandbox.workflow.migrations.0002_append_only").REVOKE
    audit_sql = import_module("sandbox.audit.migrations.0002_append_only").Migration
    audit_statement = audit_sql.operations[0].sql

    for statement, table in (
        (workflow_sql, "workflow_workflowtransition"),
        (audit_statement, "audit_auditevent"),
    ):
        assert "REVOKE UPDATE, DELETE" in statement
        assert table in statement


@pytest.fixture
def application_with_history():
    application = ApplicationFactory.create()
    owner = UserFactory.create()
    MembershipFactory.create(organisation=application.product.organisation, user=owner)
    transition(application=application, action="SUBMIT", actor=owner)
    return application


@pytest.fixture
def probe_role():
    """A non-superuser role, standing in for a correctly provisioned app role."""
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {PROBE_ROLE} NOLOGIN")
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {PROBE_ROLE}")
        for table in APPEND_ONLY_TABLES:
            cursor.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {PROBE_ROLE}",
            )
            # the statement the migrations ship, aimed at this role
            cursor.execute(f"REVOKE UPDATE, DELETE ON {table} FROM {PROBE_ROLE}")
    yield PROBE_ROLE
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")


@contextlib.contextmanager
def as_probe(cursor):
    """Run statements as the probe role.

    The caller must wrap a failing statement in its own `atomic()` block: a
    permission error aborts the transaction, and `RESET ROLE` cannot run until
    a savepoint rollback has made it usable again.
    """
    cursor.execute(f"SET ROLE {PROBE_ROLE}")
    try:
        yield
    finally:
        cursor.execute("RESET ROLE")


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_a_non_superuser_role_cannot_update(
    table,
    application_with_history,
    probe_role,
):
    with (
        connection.cursor() as cursor,
        as_probe(cursor),
        pytest.raises(ProgrammingError),
        transaction.atomic(),
    ):
        cursor.execute(f"UPDATE {table} SET id = id")  # noqa: S608 - table is a local constant


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_a_non_superuser_role_cannot_delete(
    table,
    application_with_history,
    probe_role,
):
    with (
        connection.cursor() as cursor,
        as_probe(cursor),
        pytest.raises(ProgrammingError),
        transaction.atomic(),
    ):
        cursor.execute(f"DELETE FROM {table}")  # noqa: S608 - table is a local constant


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_a_non_superuser_role_can_still_read(
    table,
    application_with_history,
    probe_role,
):
    """Append-only, not read-only: the app must keep reading and writing rows."""
    with connection.cursor() as cursor, as_probe(cursor):
        cursor.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - local constant
        assert cursor.fetchone()[0] >= 1


def test_the_local_role_is_a_superuser_so_the_revoke_is_inert_here():
    """Documents why the tests above use a probe role.

    If this ever fails, the local/CI database stopped handing out superuser and
    the revoke is live for the app role too — delete this test and celebrate.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT usesuper FROM pg_user WHERE usename = current_user",
        )
        assert cursor.fetchone()[0] is True
