import pytest
from django.core.exceptions import ImproperlyConfigured

from config.settings.guards import assert_isolated_local_environment
from config.settings.guards import assert_staff_mfa_is_required

LOCAL_DB = {"default": {"HOST": "postgres"}}
REMOTE_DB = {"default": {"HOST": "sandbox-db.internal.abdm.gov.in"}}
LOCAL_REDIS = "redis://redis:6379/0"
REMOTE_REDIS = "rediss://cache.internal.abdm.gov.in:6379/0"


def test_local_debug_stack_is_allowed():
    assert_isolated_local_environment(True, LOCAL_DB, LOCAL_REDIS)  # noqa: FBT003


def test_production_stack_is_allowed_without_debug():
    assert_isolated_local_environment(False, REMOTE_DB, REMOTE_REDIS)  # noqa: FBT003


@pytest.mark.parametrize(
    ("databases", "redis_url"),
    [
        (REMOTE_DB, LOCAL_REDIS),
        (LOCAL_DB, REMOTE_REDIS),
        (REMOTE_DB, REMOTE_REDIS),
    ],
)
def test_debug_against_shared_infrastructure_refuses_to_boot(databases, redis_url):
    with pytest.raises(ImproperlyConfigured):
        assert_isolated_local_environment(True, databases, redis_url)  # noqa: FBT003


def test_staff_mfa_may_be_relaxed_only_while_debugging():
    assert_staff_mfa_is_required(True, False)  # noqa: FBT003
    assert_staff_mfa_is_required(True, True)  # noqa: FBT003
    assert_staff_mfa_is_required(False, True)  # noqa: FBT003


def test_disabling_staff_mfa_outside_debug_refuses_to_boot():
    """The console and the admin are what a stolen staff password reaches."""
    with pytest.raises(ImproperlyConfigured):
        assert_staff_mfa_is_required(False, False)  # noqa: FBT003
