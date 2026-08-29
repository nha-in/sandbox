from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from sandbox.organisations.models import Membership
from sandbox.organisations.models import MembershipRole
from sandbox.organisations.models import Organisation
from sandbox.organisations.models import OrganisationKind
from sandbox.organisations.models import Product
from sandbox.users.tests.factories import UserFactory


class OrganisationFactory(DjangoModelFactory[Organisation]):
    name = factory.Sequence(lambda n: f"Organisation {n}")
    slug = factory.Sequence(lambda n: f"organisation-{n}")
    kind = OrganisationKind.ORGANIZATION

    class Meta:
        model = Organisation


class ProductFactory(DjangoModelFactory[Product]):
    organisation = factory.SubFactory(OrganisationFactory)
    name = factory.Sequence(lambda n: f"Product {n}")
    slug = factory.Sequence(lambda n: f"product-{n}")

    class Meta:
        model = Product


class MembershipFactory(DjangoModelFactory[Membership]):
    organisation = factory.SubFactory(OrganisationFactory)
    user = factory.SubFactory(UserFactory)
    role = MembershipRole.OWNER

    class Meta:
        model = Membership
