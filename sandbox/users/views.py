from __future__ import annotations

from typing import TYPE_CHECKING

from allauth.mfa.models import Authenticator
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DetailView
from django.views.generic import RedirectView
from django.views.generic import UpdateView

from sandbox.integrations.ports import NotificationChannel
from sandbox.users.forms import UserProfileForm
from sandbox.users.models import User
from sandbox.users.services import request_otp
from sandbox.users.services import seconds_until_resend
from sandbox.users.services import verify_otp
from sandbox.utils.errors import DomainError

if TYPE_CHECKING:
    from django.db.models import QuerySet


class UserDetailView(LoginRequiredMixin, DetailView):
    """Your own account page, and only ever your own.

    The queryset is the access control; `external_id` only keeps integer pks
    out of URLs (A2). Someone else's id therefore 404s rather than 403s.
    """

    model = User
    slug_field = "external_id"
    slug_url_kwarg = "external_id"

    def get_queryset(self) -> QuerySet[User]:
        assert self.request.user.is_authenticated  # type guard
        return User.objects.filter(external_id=self.request.user.external_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = UserProfileForm(instance=self.object)
        # Read from allauth's own table rather than a flag of our own: it is
        # the thing the login actually checks.
        context["has_totp"] = Authenticator.objects.filter(
            user=self.object,
            type=Authenticator.Type.TOTP,
        ).exists()
        return context

    def post(self, request, *args, **kwargs):
        """Editing your name is the screen's own act, not a second page."""
        self.object = self.get_object()
        form = UserProfileForm(request.POST, instance=self.object)
        if form.is_valid():
            form.save()
            messages.success(request, _("Your profile has been updated."))
            return redirect(self.object.get_absolute_url())
        context = self.get_context_data(object=self.object)
        context["form"] = form
        return self.render_to_response(context)


user_detail_view = UserDetailView.as_view()


class UserUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = User
    fields = ["name"]
    success_message = _("Information successfully updated")

    def get_success_url(self) -> str:
        assert self.request.user.is_authenticated  # type guard
        return self.request.user.get_absolute_url()

    def get_object(self, queryset: QuerySet | None = None) -> User:
        assert self.request.user.is_authenticated  # type guard
        return self.request.user


user_update_view = UserUpdateView.as_view()


class UserRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self) -> str:
        assert self.request.user.is_authenticated  # type guard
        # Where signing in lands. Staff hold no membership, so the integrator
        # dashboard 404s for them and the profile page is a dead end — the
        # console is the only screen they came here for.
        if self.request.user.is_staff:
            return reverse("console:queue")
        return reverse(
            "users:detail",
            kwargs={"external_id": self.request.user.external_id},
        )


user_redirect_view = UserRedirectView.as_view()


class ContactVerificationView(LoginRequiredMixin, View):
    """The gate every signed-in user passes before the rest of the portal opens."""

    template_name = "users/verify_contacts.html"

    def get(self, request):
        return render(request, self.template_name, self._context(request.user))

    def post(self, request):
        channel = (
            NotificationChannel.EMAIL
            if request.POST.get("channel") == NotificationChannel.EMAIL
            else NotificationChannel.SMS
        )
        identity = (
            request.user.email
            if channel is NotificationChannel.EMAIL
            else request.user.phone
        )

        try:
            if "send" in request.POST:
                request.session[_challenge_key(channel)] = request_otp(
                    identity=identity,
                    channel=channel,
                )
                messages.success(request, _("We sent you a code."))
            else:
                verify_otp(
                    user=request.user,
                    identity=identity,
                    channel=channel,
                    challenge=request.session.get(_challenge_key(channel), ""),
                    code=request.POST.get("code", ""),
                )
                request.session.pop(_challenge_key(channel), None)
                messages.success(request, _("Verified."))
        except DomainError as exc:
            messages.error(request, exc.message)

        return redirect(reverse("users:verify_contacts"))

    @staticmethod
    def _context(user):
        return {
            "all_verified": bool(user.email_verified_at and user.phone_verified_at),
            "items": [
                {
                    "label": _("Email"),
                    "channel": NotificationChannel.EMAIL,
                    "identity": user.email,
                    "verified": user.email_verified_at is not None,
                    "cooldown": seconds_until_resend(user.email),
                },
                {
                    "label": _("Phone"),
                    "channel": NotificationChannel.SMS,
                    "identity": user.phone,
                    "verified": user.phone_verified_at is not None,
                    "cooldown": seconds_until_resend(user.phone) if user.phone else 0,
                },
            ],
        }


def _challenge_key(channel: str) -> str:
    return f"otp_challenge_{channel}"


contact_verification_view = ContactVerificationView.as_view()
