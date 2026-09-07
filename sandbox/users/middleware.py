from allauth.mfa.adapter import get_adapter as get_mfa_adapter
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class StaffMfaRequiredMiddleware:
    """Staff owe TOTP before the console opens to them.

    allauth has no "MFA required" setting, and the console and admin are where
    a stolen password does the most damage. The applicant half of the original
    middleware — OTP on both contacts — waits on `User.email_verified_at` and
    `phone_verified_at`, which do not exist yet (plan 12 §8.2).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and user.is_staff
            and settings.STAFF_MFA_REQUIRED
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
        # The destination must be exempt or the redirect loops; allauth's MFA
        # setup lives under /accounts/, which also keeps logout reachable.
        exempt = ("/accounts/", settings.STATIC_URL, settings.MEDIA_URL)
        return path.startswith(tuple(p for p in exempt if p))
