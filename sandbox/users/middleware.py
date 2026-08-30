from allauth.mfa.adapter import get_adapter as get_mfa_adapter
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class VerificationRequiredMiddleware:
    """Every signed-in user owes one proof before the portal opens to them.

    Staff owe TOTP: allauth has no "MFA required" setting, and the console and
    admin are where a stolen password does the most damage. Everyone else owes
    OTP on both contacts. The fork is `is_staff` because that is the line
    between the two populations — console users are created, integrators
    enrol — and neither obligation means anything for the other side.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or self._is_exempt(request.path):
            return self.get_response(request)

        if user.is_staff:
            if settings.STAFF_MFA_REQUIRED and not get_mfa_adapter().is_mfa_enabled(
                user,
            ):
                messages.warning(
                    request,
                    _("Set up two-factor authentication to continue."),
                )
                return redirect(reverse("mfa_activate_totp"))
        elif not (user.email_verified_at and user.phone_verified_at):
            return redirect(reverse("users:verify_contacts"))

        return self.get_response(request)

    @staticmethod
    def _is_exempt(path: str) -> bool:
        # Both destinations must be exempt or the redirect loops; allauth's MFA
        # setup lives under /accounts/, which also keeps logout reachable.
        exempt = (
            "/accounts/",
            reverse("users:verify_contacts"),
            settings.STATIC_URL,
            settings.MEDIA_URL,
        )
        return path.startswith(tuple(p for p in exempt if p))
