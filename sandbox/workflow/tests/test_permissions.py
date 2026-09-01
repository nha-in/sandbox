"""The registry's permissions must exist, or authority fails closed and silent.

`has_perm` answers `False` identically for "this user lacks it" and "nobody
ever created it", so a permission a workflow names but the database has never
heard of locks out an entire review team with no error anywhere. These tests
are the difference between that and a red build.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission

from sandbox.workflow.registry import WORKFLOWS
from sandbox.workflow.registry import named_permissions
from sandbox.workflow.registry import permission_labels
from sandbox.workflow.registry import workflows_visible_to

pytestmark = pytest.mark.django_db


def test_every_permission_a_workflow_names_exists():
    existing = {
        f"workflow.{codename}"
        for codename in Permission.objects.filter(
            content_type__app_label="workflow",
        ).values_list("codename", flat=True)
    }

    assert named_permissions() <= existing


def test_the_old_global_permissions_are_not_recreated():
    """`approve_application` and friends were `Meta.permissions` until authority
    became per programme. Permissions are built from the current model state,
    so a fresh database never mints them again — a stale row in an
    already-migrated database is inert, but a regenerated one would be a global
    grant that outranks every team boundary.
    """
    stale = Permission.objects.filter(
        content_type__app_label="workflow",
        codename__endswith="_application",
    )

    assert not stale.exists()


def test_every_declared_permission_carries_a_label():
    """The role screen lists these to an admin choosing what a team may do."""
    labels = permission_labels()

    assert named_permissions() <= set(labels)
    assert all(labels.values())


def test_permissions_are_scoped_to_a_programme():
    """A name shared across programmes would let one team decide another's
    applications, which is the whole reason these are not global."""
    for workflow in WORKFLOWS.values():
        for name in workflow.permissions:
            assert name.endswith(f"_{workflow.programme}"), name


def test_a_programmes_workflows_share_one_set():
    """One team reviews an ABDM enrollment and the exit that follows it."""
    by_programme: dict[str, list[dict[str, str]]] = {}
    for workflow in WORKFLOWS.values():
        by_programme.setdefault(workflow.programme, []).append(workflow.permissions)

    for sets_ in by_programme.values():
        assert all(declared == sets_[0] for declared in sets_)


def test_visibility_is_read_from_the_permission(django_user_model):
    user = django_user_model.objects.create_user(
        email="nobody@example.gov.in",
        password="x",  # noqa: S106
    )

    assert workflows_visible_to(user) == ()
