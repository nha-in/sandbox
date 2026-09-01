from __future__ import annotations

import pytest
from django.http import Http404

from sandbox.applications.models import ApplicationState
from sandbox.applications.selectors import DECLARED
from sandbox.applications.selectors import application_detail
from sandbox.applications.selectors import applications_for_organisation
from sandbox.applications.selectors import console_queue
from sandbox.applications.selectors import coverage
from sandbox.applications.selectors import milestone_graph
from sandbox.applications.selectors import products_available_for
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.workflow import engine

pytestmark = pytest.mark.django_db


def test_applications_for_organisation_scopes_via_product():
    org_a = OrganisationFactory.create()
    org_b = OrganisationFactory.create()
    application_a = ApplicationFactory.create(
        product=ProductFactory.create(organisation=org_a),
    )
    ApplicationFactory.create(product=ProductFactory.create(organisation=org_b))

    assert list(applications_for_organisation(org_a)) == [application_a]


def test_application_detail_returns_own_organisations_application():
    org = OrganisationFactory.create()
    application = ApplicationFactory.create(
        product=ProductFactory.create(organisation=org),
    )

    assert application_detail(org, application.external_id) == application


def test_application_detail_wrong_organisation_is_404():
    org_a = OrganisationFactory.create()
    org_b = OrganisationFactory.create()
    application = ApplicationFactory.create(
        product=ProductFactory.create(organisation=org_b),
    )

    with pytest.raises(Http404):
        application_detail(org_a, application.external_id)


def test_console_queue_filters_by_kind_and_state():
    matching = ApplicationFactory.create(state=ApplicationState.SUBMITTED)
    ApplicationFactory.create(state=ApplicationState.DRAFT)

    results = list(
        console_queue(
            workflow_key=matching.workflow_key,
            state=ApplicationState.SUBMITTED,
        ),
    )

    assert results == [matching]


def test_console_queue_without_filters_returns_everything():
    ApplicationFactory.create()
    ApplicationFactory.create()

    assert console_queue().count() == 2  # noqa: PLR2004


def test_products_available_excludes_one_with_a_live_application():
    organisation = OrganisationFactory.create()
    taken = ProductFactory.create(organisation=organisation)
    free = ProductFactory.create(organisation=organisation)
    ApplicationFactory.create(product=taken, state=ApplicationState.SUBMITTED)

    available = products_available_for(organisation, "ABDM")

    assert list(available) == [free]


@pytest.mark.parametrize(
    "released_state",
    [ApplicationState.REJECTED, ApplicationState.WITHDRAWN],
)
def test_products_available_includes_one_whose_application_was_released(
    released_state,
):
    organisation = OrganisationFactory.create()
    product = ProductFactory.create(organisation=organisation)
    ApplicationFactory.create(product=product, state=released_state)

    available = products_available_for(organisation, "ABDM")

    assert list(available) == [product]


def test_products_available_is_scoped_to_the_organisation():
    organisation = OrganisationFactory.create()
    mine = ProductFactory.create(organisation=organisation)
    ProductFactory.create(organisation=OrganisationFactory.create())

    available = products_available_for(organisation, "ABDM")

    assert list(available) == [mine]


def test_products_available_ignores_another_kinds_application():
    organisation = OrganisationFactory.create()
    product = ProductFactory.create(organisation=organisation)
    ApplicationFactory.create(
        product=product,
        workflow_key="HCX",
        state=ApplicationState.SUBMITTED,
    )

    available = products_available_for(organisation, "ABDM")

    assert list(available) == [product]


def test_milestone_graph_hangs_dependents_off_their_prerequisite():
    """M2 and M3 both name M1, and neither names the other."""
    application = ApplicationFactory.create()

    graph = milestone_graph(application)

    roots = {group["root"].key for group in graph}
    assert "m1" in roots
    m1 = next(group for group in graph if group["root"].key == "m1")
    assert [row.key for row in m1["dependents"]] == ["m2", "m3"]


def test_a_milestone_that_depends_on_nothing_is_its_own_root():
    application = ApplicationFactory.create()

    graph = milestone_graph(application)

    for group in graph:
        assert group["root"].depends_on == ()


def test_coverage_counts_what_a_solution_type_still_needs():
    """HMIS needs three milestones; a fresh application has declared none."""
    application = ApplicationFactory.create()

    rows = coverage(application)

    assert [row.solution_type for row in rows] == ["HMIS"]
    assert rows[0].outstanding == len(rows[0].cells)
    assert not rows[0].is_live


def test_declaring_a_milestone_does_not_make_it_live():
    """`outstanding` counts what is not in production, and only an approved exit
    puts it there. Declaring moves the cell to DECLARED and nothing else — a
    matrix that counted declarations would tell an integrator they were done."""
    application = ApplicationFactory.create(state=ApplicationState.PROVISIONED)
    MembershipFactory.create(
        organisation=application.product.organisation,
        user=application.applicant,
    )
    before = coverage(application)[0].outstanding

    engine.submit_form(
        application=application,
        form_key="MILESTONE_M1",
        cleaned_data={"notes": "Done."},
        user=application.applicant,
    )

    row = coverage(application)[0]
    assert row.outstanding == before
    assert next(cell for cell in row.cells if cell.milestone == "M1").state == DECLARED
