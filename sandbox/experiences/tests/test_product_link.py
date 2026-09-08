"""How an application acquires its `Product` (plan 12 §1.2).

`ProductUseCase.on_submit` is the only writer. Before the table existed the
product's name went into `metadata`, and the application list searched that
copy; both of those are what these replace.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.urls import reverse

from sandbox.experiences.abdm.forms import OrganisationProfileForm
from sandbox.experiences.abdm.forms import ProductUseCaseForm
from sandbox.experiences.models import ApplicationFormSubmission
from sandbox.experiences.selectors import applications_for_user
from sandbox.experiences.selectors import filter_applications
from sandbox.experiences.services import create_application
from sandbox.experiences.services import save_form_submission
from sandbox.experiences.tests.factories import review_role_holder
from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedResourceState
from sandbox.integrations.models import ProvisionedSystem
from sandbox.organisations.models import Membership
from sandbox.organisations.models import Product
from sandbox.organisations.models import Role
from sandbox.organisations.services import match_or_create_product
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

APPLICATION_TYPE = "abdm_sandbox_access"


@pytest.fixture
def organisation(db):
    return OrganisationFactory(onboarded=True, name="Sunrise Health Systems")


@pytest.fixture
def owner(organisation):
    user = UserFactory(email="owner@vendor.in")
    Membership.objects.create(organisation=organisation, user=user, role=Role.OWNER)
    return user


@pytest.fixture
def application(organisation, owner):
    instance = create_application(
        application_type=APPLICATION_TYPE,
        organisation=organisation,
        user=owner,
    )
    _submit(instance, owner, "organisation_profile", _profile_data())
    return instance


def _profile_data() -> dict:
    return {
        "legal_entity_name": "Sunrise Health Systems",
        "organisation_type": "company",
        "registration_number": "U72900KA2024PTC123456",
        "registered_address": "42 Health Stack Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "pincode": "560038",
        "website": "https://example.com/sunrise",
        "authorised_contact_name": "Kavya Rao",
        "authorised_contact_email": "kavya@example.com",
        "authorised_contact_phone": "+91 98765 43210",
    }


def _product_data(name: str) -> dict:
    return {
        "product_name": name,
        "product_type": "hmis",
        "intent_to_integrate": "ABHA-linked records shared with consent.",
        "product_description": "An ABDM-enabled hospital information system.",
    }


_FORMS = {
    "organisation_profile": OrganisationProfileForm,
    "product_use_case": ProductUseCaseForm,
}


def _submit(application, user, form_key, data):
    form = _FORMS[form_key](data=data)
    assert form.is_valid(), form.errors
    save_form_submission(
        application=application,
        form_key=form_key,
        form=form,
        user=user,
    )
    application.refresh_from_db()
    return application


class TestOnSubmit:
    def test_submitting_the_form_attaches_a_product(self, application, owner):
        _submit(application, owner, "product_use_case", _product_data("Arogya HMIS"))

        assert application.product is not None
        assert application.product.name == "Arogya HMIS"
        assert application.product.organisation == application.organisation

    def test_the_name_no_longer_goes_into_metadata(self, application, owner):
        _submit(application, owner, "product_use_case", _product_data("Arogya HMIS"))

        assert "product_name" not in application.metadata

    def test_resubmitting_the_same_name_does_not_make_a_second_product(
        self,
        application,
        owner,
    ):
        _submit(application, owner, "product_use_case", _product_data("Arogya HMIS"))
        _submit(application, owner, "product_use_case", _product_data("arogya hmis"))

        assert Product.objects.count() == 1

    def test_renaming_moves_the_application_to_a_different_product(
        self,
        application,
        owner,
    ):
        _submit(application, owner, "product_use_case", _product_data("Arogya HMIS"))
        first = application.product

        _submit(application, owner, "product_use_case", _product_data("Arogya LIMS"))

        assert application.product != first
        assert application.product.name == "Arogya LIMS"

    def test_the_submission_still_records_its_own_answers(self, application, owner):
        """`on_submit` is an effect beside the submission, not instead of it."""
        _submit(application, owner, "product_use_case", _product_data("Arogya HMIS"))

        submission = ApplicationFormSubmission.objects.get(
            application=application,
            form_key="product_use_case",
        )
        assert submission.data["product_name"] == "Arogya HMIS"


class TestSearch:
    def test_the_list_finds_an_application_by_product_name(self, application, owner):
        """The search read `metadata.product_name`, a copy kept only to be
        filterable. It reads the FK now."""
        _submit(application, owner, "product_use_case", _product_data("Arogya HMIS"))

        found = filter_applications(applications_for_user(owner), {"q": "arogya"})

        assert list(found) == [application]

    def test_an_application_with_no_product_is_not_matched_by_a_name(
        self,
        application,
        owner,
    ):
        found = filter_applications(applications_for_user(owner), {"q": "arogya"})

        assert list(found) == []


class TestWhatTheScreensShow:
    """Six templates read `metadata.product_name` before the FK existed. A
    submission that no longer writes that key would have blanked every one."""

    def test_the_vendor_list_names_the_product(self, client, application, owner):
        _submit(application, owner, "product_use_case", _product_data("Arogya HMIS"))
        client.force_login(owner)

        body = client.get(reverse("experiences:list")).content.decode()

        assert "Arogya HMIS" in body

    def test_the_vendor_detail_names_the_product(self, client, application, owner):
        _submit(application, owner, "product_use_case", _product_data("Arogya HMIS"))
        client.force_login(owner)

        body = client.get(
            reverse("experiences:detail", kwargs={"reference": application.reference}),
        ).content.decode()

        assert "Arogya HMIS" in body

    def test_the_console_list_names_the_product(
        self,
        client,
        application,
        owner,
        enable_mfa,
    ):
        _submit(application, owner, "product_use_case", _product_data("Arogya HMIS"))
        reviewer = review_role_holder()
        reviewer.is_staff = True
        reviewer.save(update_fields=["is_staff"])
        # Making an account staff subjects it to StaffMfaRequiredMiddleware.
        enable_mfa(reviewer)
        client.force_login(reviewer)

        body = client.get(reverse("staff:applications")).content.decode()

        assert "Arogya HMIS" in body


class TestOrganisationInvariant:
    def test_an_application_cannot_point_at_another_organisations_product(
        self,
        application,
    ):
        """A cross-tenant reference. It spans two tables, so no database
        constraint expresses it — the model does."""
        stranger = OrganisationFactory(onboarded=True, name="Northwind")
        application.product = match_or_create_product(
            organisation=stranger,
            name="Their product",
        )

        with pytest.raises(ValidationError) as caught:
            application.full_clean()

        assert "product" in caught.value.message_dict

    def test_its_own_organisations_product_is_accepted(self, application):
        application.product = match_or_create_product(
            organisation=application.organisation,
            name="Ours",
        )

        application.full_clean(exclude=["reference", "title", "status"])


class TestTheExitInheritsItsProduct:
    """An exit is about a product it never asks for: `ProductUseCase` is on the
    first gate, so the predecessor carries it (plan 12 §1.2)."""

    def test_opening_an_exit_from_a_sandbox_access_carries_its_product_over(
        self,
        application,
        owner,
    ):
        _submit(application, owner, "product_use_case", _product_data("Arogya HMIS"))
        application.status = "approved"
        application.save(update_fields=["status"])
        ProvisionedResource.objects.create(
            application=application,
            system=ProvisionedSystem.KEYCLOAK,
            external_ref="keycloak-test",
            public_ref="SBX-0001",
            state=ProvisionedResourceState.ACTIVE,
        )

        exit_application = create_application(
            application_type="abdm_milestone_exit",
            organisation=application.organisation,
            user=owner,
            predecessor=application,
        )

        assert exit_application.product == application.product
        assert exit_application.metadata["predecessor"] == application.reference
        assert Product.objects.count() == 1

    def test_an_exit_cannot_follow_another_organisations_application(
        self,
        application,
        owner,
    ):
        stranger_org = OrganisationFactory(onboarded=True, name="Northwind")
        outsider = UserFactory(email="other@vendor.in")
        Membership.objects.create(
            organisation=stranger_org,
            user=outsider,
            role=Role.OWNER,
        )
        stranger = create_application(
            application_type="abdm_sandbox_access",
            organisation=stranger_org,
            user=outsider,
        )

        with pytest.raises(PermissionDenied):
            create_application(
                application_type="abdm_milestone_exit",
                organisation=application.organisation,
                user=owner,
                predecessor=stranger,
            )


class TestTheProductFormsOwnFields:
    """All four answers are per registration, not per organisation: in the
    legacy dump most organisations that registered more than once gave a
    different solution type, and a sixth gave a different intent."""

    def test_other_must_say_which_other(self):
        form = ProductUseCaseForm(
            data={**_product_data("Arogya HMIS"), "product_type": "other"},
        )

        assert not form.is_valid()
        assert "product_type_other" in form.errors

    def test_other_is_accepted_once_named(self):
        form = ProductUseCaseForm(
            data={
                **_product_data("Arogya HMIS"),
                "product_type": "other",
                "product_type_other": "Radiology reporting platform",
            },
        )

        assert form.is_valid(), form.errors

    def test_a_named_type_needs_no_other(self):
        form = ProductUseCaseForm(data=_product_data("Arogya HMIS"))

        assert form.is_valid(), form.errors

    def test_intent_is_required(self):
        data = _product_data("Arogya HMIS")
        del data["intent_to_integrate"]

        form = ProductUseCaseForm(data=data)

        assert not form.is_valid()
        assert "intent_to_integrate" in form.errors

    def test_two_products_in_one_organisation_carry_their_own_answers(
        self,
        application,
        owner,
    ):
        """The reason both live here rather than on the organisation."""
        _submit(application, owner, "product_use_case", _product_data("Arogya HMIS"))
        first = application.submissions.get(form_key="product_use_case").data

        second_data = {
            **_product_data("Arogya LIMS"),
            "intent_to_integrate": "Lab reports to ABHA addresses.",
        }
        _submit(application, owner, "product_use_case", second_data)
        second = application.submissions.get(
            form_key="product_use_case",
            is_current=True,
        ).data

        assert first["intent_to_integrate"] != second["intent_to_integrate"]
