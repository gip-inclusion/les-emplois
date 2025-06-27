from django.apps import AppConfig
from django.utils.text import Truncator


class SmartTruncator(Truncator):
    def __init__(self, text):
        if hasattr(text, "display_with_pii"):
            text = text.display_with_pii
        super().__init__(text)


class UtilsAppConfig(AppConfig):
    name = "itou.utils"
    verbose_name = "utils"

    def ready(self):
        from django.contrib.admin import widgets

        widgets.Truncator = SmartTruncator
