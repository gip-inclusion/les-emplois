from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AspConfig(AppConfig):
    name = "itou.asp"
    verbose_name = _("Référentiels de données ASP")
