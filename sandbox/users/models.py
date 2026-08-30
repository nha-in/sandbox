import uuid
from typing import ClassVar

from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db.models import CharField
from django.db.models import DateTimeField
from django.db.models import EmailField
from django.db.models import UUIDField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .managers import UserManager

phone_validator = RegexValidator(
    regex=r"^\+?[0-9]{7,15}$",
    message=_("Enter a phone number with 7-15 digits, optionally starting with '+'."),
)


class User(AbstractUser):
    """
    Default custom user model for ABDM Sandbox.
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    # First and last name do not cover name patterns around the globe
    name = CharField(_("Name of User"), blank=True, max_length=255)
    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]
    email = EmailField(_("email address"), unique=True)
    username = None  # type: ignore[assignment]

    # care base-model convention: the only identifier that leaves the system
    external_id = UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )
    phone = CharField(
        _("phone number"),
        max_length=20,
        blank=True,
        default="",
        validators=[phone_validator],
    )
    email_verified_at = DateTimeField(_("email verified at"), null=True, blank=True)
    phone_verified_at = DateTimeField(_("phone verified at"), null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects: ClassVar[UserManager] = UserManager()

    def get_absolute_url(self) -> str:
        """Get URL for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"external_id": self.external_id})
