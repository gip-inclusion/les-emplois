from django.apps import AppConfig
from django.core.checks import Tags, register

from itou.utils.checks import check_verbose_name_lower


class UtilsAppConfig(AppConfig):
    name = "itou.utils"
    verbose_name = "utils"

    def ready(self):
        super().ready()
        register(Tags.models)(check_verbose_name_lower)
