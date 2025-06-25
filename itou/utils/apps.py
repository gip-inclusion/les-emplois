from django.apps import AppConfig
from django.utils.text import Truncator


class PIIAwareTruncator(Truncator):
    def __init__(self, text):
        if hasattr(text, "display_with_pii"):
            text = text.display_with_pii
        super().__init__(text)


class UtilsAppConfig(AppConfig):
    name = "itou.utils"
    verbose_name = "utils"

    def ready(self):
        from django.contrib.admin import widgets

        # This allows models to be displayed in the admin forms via their display_with_pii property
        # instead of the default __str__ method when such property exists.
        widgets.Truncator = PIIAwareTruncator
