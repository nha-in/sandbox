from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from sandbox.catalog.models import Milestone


class MilestoneFactory(DjangoModelFactory[Milestone]):
    key = factory.Sequence(lambda n: f"milestone-{n}")
    title = factory.Sequence(lambda n: f"Milestone {n}")
    track = "SANDBOX"
    order = factory.Sequence(lambda n: n)
    is_active = True

    class Meta:
        model = Milestone
