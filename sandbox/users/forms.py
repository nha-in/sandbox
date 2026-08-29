from allauth.account.forms import SignupForm
from allauth.socialaccount.forms import SignupForm as SocialSignupForm
from django.contrib.auth import forms as admin_forms
from django.forms import CharField
from django.forms import EmailField
from django.utils.translation import gettext_lazy as _

from .models import User
from .models import phone_validator


class UserAdminChangeForm(admin_forms.UserChangeForm):
    class Meta(admin_forms.UserChangeForm.Meta):
        model = User
        field_classes = {"email": EmailField}


class UserAdminCreationForm(admin_forms.AdminUserCreationForm):
    """
    Form for User Creation in the Admin Area.
    To change user signup, see UserSignupForm and UserSocialSignupForm.
    """

    class Meta(admin_forms.UserCreationForm.Meta):
        model = User
        fields = ("email",)
        field_classes = {"email": EmailField}
        error_messages = {
            "email": {"unique": _("This email has already been taken.")},
        }


class UserSignupForm(SignupForm):
    """Collects the phone up front: submit is blocked until it is verified (A4),
    so the enrollment wizard has nothing to chase."""

    phone = CharField(
        max_length=20,
        label=_("Phone number"),
        validators=[phone_validator],
    )

    def save(self, request):
        user = super().save(request)
        user.phone = self.cleaned_data["phone"]
        user.save(update_fields=["phone"])
        return user


class UserSocialSignupForm(SocialSignupForm):
    """
    Renders the form when user has signed up using social accounts.
    Default fields will be added automatically.
    See UserSignupForm otherwise.
    """
