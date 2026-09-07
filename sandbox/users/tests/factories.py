from __future__ import annotations

from factory import Faker
from factory import post_generation
from factory.django import DjangoModelFactory

from sandbox.users.models import User


class UserFactory(DjangoModelFactory[User]):
    email = Faker("email")
    name = Faker("name")

    @post_generation
    def password(self: User, create: bool, extracted: str | None, **kwargs):  # noqa: FBT001
        password = (
            extracted
            if extracted
            else Faker(
                "password",
                length=42,
                special_chars=True,
                digits=True,
                upper_case=True,
                lower_case=True,
            ).evaluate(None, None, extra={"locale": None})
        )
        self.set_password(password)
        if create:
            self.save()

    @post_generation
    def mfa(self: User, create: bool, extracted: bool | None, **kwargs):  # noqa: FBT001
        """Staff get TOTP, because `StaffMfaRequiredMiddleware` means a staff
        account without it cannot reach anything. Pass `mfa=False` to build the
        account that gets redirected."""
        if not create or not self.is_staff or extracted is False:
            return
        from allauth.mfa.totp.internal import auth  # noqa: PLC0415

        auth.TOTP.activate(self, auth.generate_totp_secret())

    class Meta:
        model = User
        django_get_or_create = ["email"]
        skip_postgeneration_save = True
