"""The two read shapes: what is current, and what happened."""

from __future__ import annotations

import pytest

from sandbox.declarations import selectors
from sandbox.declarations import services
from sandbox.declarations.models import DeclarationKind
from sandbox.declarations.models import DeclarationState
from sandbox.organisations.tests.factories import OrganisationFactory

pytestmark = pytest.mark.django_db

#: one milestone claim plus the two-milestone exit
EXPECTED_CLAIMS = 3


def test_coverage_returns_one_row_per_current_claim(
    application,
    milestone,
    other_milestone,
    member,
):
    services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    services.submit_exit_declaration(
        application=application,
        milestones=[milestone, other_milestone],
        actor=member,
    )

    coverage = selectors.milestone_coverage(application)
    assert coverage.count() == EXPECTED_CLAIMS
    assert {(claim.kind, claim.milestone.key) for claim in coverage} == {
        (DeclarationKind.MILESTONE, milestone.key),
        (DeclarationKind.EXIT, milestone.key),
        (DeclarationKind.EXIT, other_milestone.key),
    }


def test_coverage_hides_superseded_claims(application, milestone, member):
    services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    latest = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )

    assert selectors.milestone_coverage(application).get().declaration == latest


def test_coverage_keeps_a_rejected_claim_until_it_is_replaced(
    application,
    milestone,
    member,
):
    """A rejection does not free the milestone; the resubmission does."""
    rejected = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    rejected.state = DeclarationState.REJECTED
    rejected.save(update_fields=["state"])

    claim = selectors.milestone_coverage(application).get()
    assert claim.declaration == rejected
    assert claim.declaration.state == DeclarationState.REJECTED


def test_an_undeclared_milestone_is_simply_absent(application, milestone, member):
    services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    covered = {
        claim.milestone.key for claim in selectors.milestone_coverage(application)
    }
    assert "never-declared" not in covered


def test_the_timeline_shows_superseded_declarations_too(
    application,
    milestone,
    member,
):
    first = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    second = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )

    timeline = list(selectors.declaration_timeline(application))
    assert set(timeline) == {first, second}


def test_the_timeline_is_newest_first(application, milestone, other_milestone, member):
    services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    latest = services.submit_milestone_declaration(
        application=application,
        milestone=other_milestone,
        actor=member,
    )

    assert next(iter(selectors.declaration_timeline(application))) == latest


def test_the_timeline_carries_the_supersession_link(
    application,
    milestone,
    member,
):
    """The UI marks older attempts without a second query."""
    first = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    second = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )

    timeline = {d.pk: d for d in selectors.declaration_timeline(application)}
    claim = timeline[first.pk].milestones.all()[0]
    assert claim.superseded_by == second


def test_declarations_are_scoped_to_the_owning_organisation(
    application,
    organisation,
    milestone,
    member,
):
    services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )

    assert selectors.declarations_for_organisation(organisation).count() == 1
    assert not selectors.declarations_for_organisation(
        OrganisationFactory.create(),
    ).exists()
