from __future__ import annotations

from typing import TYPE_CHECKING

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
from sandbox.users.models import User
from sandbox.users.services import request_otp
from sandbox.users.services import seconds_until_resend
from sandbox.users.services import verify_otp
from sandbox.utils.errors import DomainError

if TYPE_CHECKING:
    from django.db.models import QuerySet


class UserDetailView(LoginRequiredMixin, DetailView):
    model = User
    slug_field = "id"
    slug_url_kwarg = "id"


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
        return reverse("users:detail", kwargs={"pk": self.request.user.pk})


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
