from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class OrganisationsConfig(AppConfig):
    name = "sandbox.organisations"
    verbose_name = _("Organisations")
