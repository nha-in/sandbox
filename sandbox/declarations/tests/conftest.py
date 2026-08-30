"""Shared fixtures for the declarations suite.

`mock_s3` gives every test a real S3 conversation against `moto`, so presigning
and object storage are exercised rather than stubbed — the bucket is created
per test and thrown away with it.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.catalog.tests.factories import MilestoneFactory
from sandbox.declarations import services
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import VerifiedUserFactory

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
XLSX = b"PK\x03\x04" + b"\x00" * 60
XLS = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 60
CSV = b"milestone,status\nm1,complete\n"


@pytest.fixture(autouse=True)
def _no_scanners():
    services.clear_scanners()
    yield
    services.clear_scanners()


@pytest.fixture
def organisation(db):
    return OrganisationFactory.create()


@pytest.fixture
def member(organisation):
    user = VerifiedUserFactory.create()
    MembershipFactory.create(organisation=organisation, user=user)
    return user


@pytest.fixture
def application(organisation, member):
    return ApplicationFactory.create(
        product=ProductFactory.create(organisation=organisation),
        applicant=member,
        state=ApplicationState.PROVISIONED,
    )


@pytest.fixture
def milestone(db):
    return MilestoneFactory.create(key="m1")


@pytest.fixture
def other_milestone(db):
    return MilestoneFactory.create(key="m2")


def upload(name: str = "evidence.pdf", content: bytes = PDF) -> SimpleUploadedFile:
    """A file as the browser would send it — content_type is attacker-chosen."""
    return SimpleUploadedFile(name, content, content_type="application/pdf")
