from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from factory import LazyFunction
from factory import Sequence
from factory import SubFactory
from factory import Trait
from factory.django import DjangoModelFactory

from sandbox.organisations.models import Invitation
from sandbox.organisations.models import Membership
from sandbox.organisations.models import Organisation
from sandbox.organisations.models import Role
from sandbox.users.tests.factories import UserFactory


class OrganisationFactory(DjangoModelFactory[Organisation]):
    name = Sequence(lambda n: f"Vendor {n} Health Systems")

    class Meta:
        model = Organisation

    class Params:
        # OrganisationFactory(onboarded=True) — past the company profile form.
        onboarded = Trait(onboarded_at=LazyFunction(timezone.now))


class MembershipFactory(DjangoModelFactory[Membership]):
    organisation = SubFactory(OrganisationFactory)
    user = SubFactory(UserFactory)
    role = Role.DEVELOPER

    class Meta:
        model = Membership


class InvitationFactory(DjangoModelFactory[Invitation]):
    organisation = SubFactory(OrganisationFactory)
    email = Sequence(lambda n: f"invitee{n}@example.in")
    role = Role.DEVELOPER

    class Meta:
        model = Invitation

    class Params:
        expired = Trait(
            expires_at=LazyFunction(lambda: timezone.now() - timedelta(days=1)),
        )
        revoked = Trait(revoked_at=LazyFunction(timezone.now))
        accepted = Trait(accepted_at=LazyFunction(timezone.now))
