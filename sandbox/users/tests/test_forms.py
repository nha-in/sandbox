"""Module for all Form Tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.translation import gettext_lazy as _

from sandbox.users.forms import UserAdminCreationForm
from sandbox.users.forms import UserSignupForm

if TYPE_CHECKING:
    from sandbox.users.models import User


class TestUserAdminCreationForm:
    """
    Test class for all tests related to the UserAdminCreationForm
    """

    def test_username_validation_error_msg(self, user: User):
        """
        Tests UserAdminCreation Form's unique validator functions correctly by testing:
            1) A new user with an existing username cannot be added.
            2) Only 1 error is raised by the UserCreation Form
            3) The desired error message is raised
        """

        # The user already exists,
        # hence cannot be created.
        form = UserAdminCreationForm(
            {
                "email": user.email,
                "password1": user.password,
                "password2": user.password,
            },
        )

        assert not form.is_valid()
        assert len(form.errors) == 1
        assert "email" in form.errors
        assert form.errors["email"][0] == _("This email has already been taken.")


class TestUserSignupForm:
    """Phone is collected at signup so the wizard has one to verify (A4)."""

    def test_signup_persists_the_phone(self, db, rf):
        form = UserSignupForm(
            data={
                "email": "newapplicant@example.com",
                "password1": "s3cure-passphrase-xyz",
                "password2": "s3cure-passphrase-xyz",
                "phone": "+919876543210",
            },
        )
        assert form.is_valid(), form.errors

        request = rf.post("/accounts/signup/")
        request.session = {}
        user = form.save(request)

        user.refresh_from_db()
        assert user.phone == "+919876543210"
        assert user.phone_verified_at is None

    def test_phone_is_required(self, db):
        form = UserSignupForm(
            data={
                "email": "nophone@example.com",
                "password1": "s3cure-passphrase-xyz",
                "password2": "s3cure-passphrase-xyz",
            },
        )
        assert not form.is_valid()
        assert "phone" in form.errors

    def test_a_malformed_phone_is_rejected(self, db):
        form = UserSignupForm(
            data={
                "email": "badphone@example.com",
                "password1": "s3cure-passphrase-xyz",
                "password2": "s3cure-passphrase-xyz",
                "phone": "not-a-number",
            },
        )
        assert not form.is_valid()
        assert "phone" in form.errors
