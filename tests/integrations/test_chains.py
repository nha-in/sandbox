"""The V0.3 exit evidence: kill a chain, re-run it, and count what reached the wire.

The ledger tests in `sandbox/integrations/tests/` prove the chain's *bookkeeping*
is idempotent. These prove the thing that actually matters — that no second
client, application or bridge was ever requested — using WireMock's request
journal rather than our own records. A ledger that wrongly believes a step ran
would satisfy the former and fail here.

The stub payloads are shaped from the legacy Java source, so they prove **our**
behaviour, not ABDM's protocol. Recording real responses is what would make them
evidence of the latter, and that needs the access B3-B6 are still waiting on.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.test import override_settings

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.integrations.hooks import register_workflow_hooks
from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedResourceState
from sandbox.integrations.models import ProvisionedSystem
from sandbox.integrations.services import retry_provisioning
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.users.models import User
from sandbox.users.tests.factories import UserFactory
from sandbox.workflow import engine as workflow_engine
from sandbox.workflow.engine import transition

pytestmark = pytest.mark.django_db

REALM = "abdm-sandbox"
DEVPORTAL = "/api/am/devportal/v3"
HIECM_API = "/api/v3"
CLIENT_UUID = "11111111-2222-3333-4444-555555555555"

# The four calls that must never happen twice.
KEYCLOAK_CREATE = f"/admin/realms/{REALM}/clients"
WSO2_CREATE = f"{DEVPORTAL}/applications"
HIECM_CREATE = f"{HIECM_API}/gateway/bridge"

KEYCLOAK_DISABLE = f"/admin/realms/{REALM}/clients/{CLIENT_UUID}"
BAD_REQUEST = 400
CREATED = 201
NO_CONTENT = 204
#: the failed bridge attempt plus the one the console retry completes
BRIDGE_ATTEMPTS = 2


def _stub_keycloak(wiremock) -> None:
    wiremock.stub(
        "POST",
        f"/realms/{REALM}/protocol/openid-connect/token",
        json_body={"access_token": "kc-token", "expires_in": 300},
    )
    wiremock.stub(
        "POST",
        f"{KEYCLOAK_CREATE}$",
        status=CREATED,
        headers={"Location": f"http://wiremock{KEYCLOAK_CREATE}/{CLIENT_UUID}"},
    )
    wiremock.stub(
        "GET",
        f"/admin/realms/{REALM}/roles/.+",
        json_body={"id": "role-1", "name": "hip"},
    )
    wiremock.stub("POST", ".*/scope-mappings/realm", status=NO_CONTENT)
    wiremock.stub(
        "GET",
        ".*/service-account-user",
        json_body={"id": "service-account-1"},
    )
    wiremock.stub("POST", ".*/role-mappings/realm", status=NO_CONTENT)
    wiremock.stub("GET", ".*/client-secret", json_body={"value": "s3cret-from-kc"})
    # PUT on the client is `disable_client`; scoped tightly so it cannot also
    # answer the create above.
    wiremock.stub("PUT", f"{KEYCLOAK_DISABLE}$", status=NO_CONTENT)


def _stub_wso2(wiremock) -> None:
    wiremock.stub("POST", "/oauth2/token", json_body={"access_token": "w-t"})
    wiremock.stub("GET", f"{WSO2_CREATE}\\?.*", json_body={"list": []})
    wiremock.stub(
        "POST",
        f"{WSO2_CREATE}$",
        json_body={"applicationId": "wso2-app-1"},
    )
    wiremock.stub(
        "GET",
        f"{DEVPORTAL}/apis\\?.*",
        json_body={
            "list": [
                {"name": "HealthIdAPI", "id": "api-1"},
                {"name": "GatewayAPI", "id": "api-2"},
            ],
        },
    )
    wiremock.stub(
        "GET",
        f"{DEVPORTAL}/subscriptions\\?.*",
        json_body={"list": []},
    )
    wiremock.stub("POST", f"{DEVPORTAL}/subscriptions/multiple", json_body={})
    wiremock.stub("POST", f"{DEVPORTAL}/applications/.+/map-keys", json_body={})


def _stub_hiecm(wiremock, *, bridge_status: int = 200) -> None:
    wiremock.stub(
        "POST",
        f"{HIECM_API}/sessions",
        json_body={"accessToken": "hiecm-token", "expiresIn": 300},
    )
    wiremock.stub("PUT", f"{HIECM_CREATE}$", status=bridge_status, json_body={})
    wiremock.stub("PATCH", f"{HIECM_CREATE}$", status=NO_CONTENT)


def _stub_everything(wiremock, *, bridge_status: int = 200) -> None:
    _stub_keycloak(wiremock)
    _stub_wso2(wiremock)
    _stub_hiecm(wiremock, bridge_status=bridge_status)


def _pointing_at(url: str):
    """Every adapter real, every base URL the pretend network."""
    return override_settings(
        INTEGRATION_PORTS={
            "IDP": "sandbox.integrations.keycloak.adapter.KeycloakIdpAdmin",
            "API_GATEWAY": "sandbox.integrations.wso2.adapter.Wso2ApiGateway",
            "BRIDGE_REGISTRY": "sandbox.integrations.hiecm.adapter.HiecmBridgeRegistry",
            "NOTIFICATION": "sandbox.integrations.fakes.FakeNotificationGateway",
        },
        KEYCLOAK_BASE_URL=url,
        KEYCLOAK_REALM=REALM,
        KEYCLOAK_ROLE_NAMES={"SANDBOX": ("hip",)},
        WSO2_BASE_URL=url,
        WSO2_DEVPORTAL_PATH=DEVPORTAL,
        WSO2_API_NAMES={"SANDBOX": ("HealthIdAPI", "GatewayAPI")},
        HIECM_BASE_URL=url,
        HIECM_API_PATH=HIECM_API,
    )


@pytest.fixture(autouse=True)
def _hooks():
    workflow_engine.clear_hooks()
    register_workflow_hooks()
    yield
    workflow_engine.clear_hooks()


@pytest.fixture
def application():
    return ApplicationFactory.create()


@pytest.fixture
def owner(application):
    user = UserFactory.create()
    MembershipFactory.create(organisation=application.product.organisation, user=user)
    return user


def _staff(*codenames: str) -> User:
    user = UserFactory.create(is_staff=True)
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename))
    return User.objects.get(pk=user.pk)


def _approve(application, owner, callbacks) -> None:
    transition(application=application, action="SUBMIT", actor=owner)
    with callbacks(execute=True):
        transition(
            application=application,
            action="APPROVE",
            actor=_staff("approve_application"),
        )
    application.refresh_from_db()


def _rerun_chain(application) -> None:
    from sandbox.integrations.tasks import complete_provisioning  # noqa: PLC0415
    from sandbox.integrations.tasks import provision_hiecm  # noqa: PLC0415
    from sandbox.integrations.tasks import provision_keycloak  # noqa: PLC0415
    from sandbox.integrations.tasks import provision_wso2  # noqa: PLC0415

    for task in (provision_keycloak, provision_wso2, provision_hiecm):
        task.delay(application.pk, "rerun")
    complete_provisioning.delay(application.pk, "rerun")


def test_the_chain_provisions_through_real_adapters(
    wiremock,
    wiremock_url,
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """Baseline: the adapters actually complete against a real HTTP server."""
    _stub_everything(wiremock)

    with _pointing_at(wiremock_url):
        _approve(application, owner, django_capture_on_commit_callbacks)

    assert application.state == ApplicationState.PROVISIONED
    assert wiremock.count("POST", KEYCLOAK_CREATE) == 1
    assert wiremock.count("POST", WSO2_CREATE) == 1
    assert wiremock.count("PUT", HIECM_CREATE) == 1


def test_re_running_a_finished_chain_creates_nothing_twice(
    wiremock,
    wiremock_url,
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """The headline. Not "the ledger says so" — the wire says so."""
    _stub_everything(wiremock)

    with _pointing_at(wiremock_url):
        _approve(application, owner, django_capture_on_commit_callbacks)
        _rerun_chain(application)

    assert wiremock.count("POST", KEYCLOAK_CREATE) == 1
    assert wiremock.count("POST", WSO2_CREATE) == 1
    assert wiremock.count("PUT", HIECM_CREATE) == 1


@override_settings(PROVISIONING_MAX_ATTEMPTS=1)
def test_a_chain_killed_at_the_last_step_resumes_without_duplicating(
    wiremock,
    wiremock_url,
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """Fail HIE-CM, then let the console retry finish only what was missing.

    The failure is a 400 rather than a 500 on purpose: `create_bridge` is a PUT,
    so B1 treats it as idempotent and retries a 5xx itself — the first draft of
    this test recovered inside the HTTP client and never reached the chain.
    """
    _stub_keycloak(wiremock)
    _stub_wso2(wiremock)
    wiremock.stub(
        "POST",
        f"{HIECM_API}/sessions",
        json_body={"accessToken": "hiecm-token", "expiresIn": 300},
    )
    wiremock.stub(
        "PUT",
        f"{HIECM_CREATE}$",
        status=BAD_REQUEST,
        scenario="bridge",
        required_state="Started",
        next_state="up",
    )
    wiremock.stub(
        "PUT",
        f"{HIECM_CREATE}$",
        status=200,
        json_body={},
        scenario="bridge",
        required_state="up",
    )

    with _pointing_at(wiremock_url):
        _approve(application, owner, django_capture_on_commit_callbacks)
        assert application.state == ApplicationState.PROVISIONING_FAILED

        with django_capture_on_commit_callbacks(execute=True):
            retry_provisioning(
                application=application,
                actor=_staff("retry_provisioning"),
            )

    application.refresh_from_db()
    assert application.state == ApplicationState.PROVISIONED
    # The two systems that succeeded were never asked a second time.
    assert wiremock.count("POST", KEYCLOAK_CREATE) == 1
    assert wiremock.count("POST", WSO2_CREATE) == 1
    assert wiremock.count("PUT", HIECM_CREATE) == BRIDGE_ATTEMPTS


def test_the_teardown_disables_each_resource_exactly_once(
    wiremock,
    wiremock_url,
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    _stub_everything(wiremock)

    with _pointing_at(wiremock_url):
        _approve(application, owner, django_capture_on_commit_callbacks)
        with django_capture_on_commit_callbacks(execute=True):
            transition(application=application, action="WITHDRAW", actor=owner)

        assert wiremock.count("PUT", KEYCLOAK_DISABLE) == 1
        assert wiremock.count("PATCH", HIECM_CREATE) == 1

        from sandbox.integrations.tasks import enqueue_teardown  # noqa: PLC0415

        with django_capture_on_commit_callbacks(execute=True):
            enqueue_teardown(application)

    # DISABLED rows are skipped, so a second teardown touches nothing.
    assert wiremock.count("PUT", KEYCLOAK_DISABLE) == 1
    assert wiremock.count("PATCH", HIECM_CREATE) == 1
    states = {row.system: row.state for row in application.provisioned_resources.all()}
    assert set(states.values()) == {ProvisionedResourceState.DISABLED}


def test_a_read_never_rotates_the_keycloak_secret(
    wiremock,
    wiremock_url,
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """Legacy's `getSecret` was a POST, so every read rotated the live secret.

    The journal is the only place this can be proven end-to-end: nothing in the
    ledger or the domain would notice a POST here.
    """
    _stub_everything(wiremock)

    with _pointing_at(wiremock_url):
        _approve(application, owner, django_capture_on_commit_callbacks)

    secret_calls = [
        entry for entry in wiremock.journal() if entry["url"].endswith("/client-secret")
    ]
    assert secret_calls
    assert {entry["method"] for entry in secret_calls} == {"GET"}


def test_the_ledger_records_what_the_wire_returned(
    wiremock,
    wiremock_url,
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """Guards the hand-off B7 depends on: the Location header becomes external_ref."""
    _stub_everything(wiremock)

    with _pointing_at(wiremock_url):
        _approve(application, owner, django_capture_on_commit_callbacks)

    keycloak = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
    )
    assert keycloak.external_ref == CLIENT_UUID
    wso2 = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.WSO2,
    )
    assert wso2.external_ref == "wso2-app-1"
