from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class OhcConfig(AppConfig):
    name = "sandbox.ohc"
    verbose_name = _("OHC console")
