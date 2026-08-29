from allauth.mfa.adapter import get_adapter as get_mfa_adapter
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class StaffMFARequiredMiddleware:
    """Staff and reviewers must finish MFA setup before using any staff surface.

    allauth has no "MFA required" setting, and the console/admin are the two
    surfaces where a stolen password is most damaging.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and user.is_staff
            and not self._is_exempt(request.path)
            and not get_mfa_adapter().is_mfa_enabled(user)
        ):
            messages.warning(
                request,
                _("Set up two-factor authentication to continue."),
            )
            return redirect(reverse("mfa_activate_totp"))
        return self.get_response(request)

    @staticmethod
    def _is_exempt(path: str) -> bool:
        exempt = ("/accounts/", settings.STATIC_URL, settings.MEDIA_URL)
        return path.startswith(tuple(p for p in exempt if p))


class ContactVerificationRequiredMiddleware:
    """Nothing in the portal opens until both contacts are OTP-verified.

    Staff are exempt: they are created by the console, not by enrolling, and
    the MFA gate above already covers them.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not user.is_staff
            and not (user.email_verified_at and user.phone_verified_at)
            and not self._is_exempt(request.path)
        ):
            return redirect(reverse("users:verify_contacts"))
        return self.get_response(request)

    @staticmethod
    def _is_exempt(path: str) -> bool:
        exempt = (
            "/accounts/",
            "/users/verify-contacts/",
            settings.STATIC_URL,
            settings.MEDIA_URL,
        )
        return path.startswith(tuple(p for p in exempt if p))
