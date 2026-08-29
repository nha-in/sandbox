"""The staff gate. A console screen cannot be added without inheriting it.

Legacy ran the reviewer UI on client-side role checks, so authority was whatever
the browser claimed. Here the gate is server-side and structural: the mixin also
supplies the nav state, so a view that forgets it renders without chrome and is
obvious in review.
"""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class ConsoleMixin(LoginRequiredMixin):
    #: highlights the matching nav item
    console_section: str = ""

    def dispatch(self, request, *args, **kwargs):
        # 403 rather than 404: the console's existence is not a secret, and its
        # URLs carry no organisation's identifiers to leak.
        if request.user.is_authenticated and not request.user.is_staff:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)  # type: ignore[misc]
        context["console_section"] = self.console_section
        return context
