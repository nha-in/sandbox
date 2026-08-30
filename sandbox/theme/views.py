"""The component gallery.

Not a product screen: it exists so a reviewer can see every primitive in every
state on one page, and so a regression in the shared CSS is visible without
hunting for a real application in the right state to reproduce it.

Two gates, both required. `DEBUG` keeps it off deployed environments entirely,
because a page that renders every state of every component is a map of the
system's shape. `is_staff` keeps it away from integrators even locally, where
DEBUG is on and their session is real.
"""

from __future__ import annotations

from django.conf import settings
from django.http import Http404
from django.views.generic import TemplateView


class StyleguideView(TemplateView):
    template_name = "pages/styleguide.html"

    def dispatch(self, request, *args, **kwargs):
        # 404, not 403: off a development machine this URL does not exist, and
        # saying "forbidden" would confirm that it does.
        if not settings.DEBUG or not request.user.is_authenticated:
            raise Http404
        if not request.user.is_staff:
            raise Http404
        return super().dispatch(request, *args, **kwargs)
