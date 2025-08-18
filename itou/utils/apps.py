from django.apps import AppConfig
from django.contrib.admin.helpers import AdminReadonlyField
from django.contrib.admin.utils import quote
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html
from django.utils.text import Truncator


class PIIAwareTruncator(Truncator):
    def __init__(self, text):
        if hasattr(text, "display_with_pii"):
            text = text.display_with_pii
        super().__init__(text)


def pii_aware_get_admin_url(self, remote_field, remote_obj):
    # Directly copied from django.contrib.admin.helpers.AdminReadonlyField.get_admin_url
    # Django 5.2.5
    url_name = "admin:%s_%s_change" % (  # noqa: UP031
        remote_field.model._meta.app_label,
        remote_field.model._meta.model_name,
    )

    # This is an extra part
    if hasattr(remote_obj, "display_with_pii"):
        remote_str = remote_obj.display_with_pii
    else:
        remote_str = str(remote_obj)
    # End of extra part
    try:
        url = reverse(
            url_name,
            args=[quote(remote_obj.pk)],
            current_app=self.model_admin.admin_site.name,
        )
        # This is modified
        return format_html('<a href="{}">{}</a>', url, remote_str)
    except NoReverseMatch:
        # This is modified
        return str(remote_str)


class UtilsAppConfig(AppConfig):
    name = "itou.utils"
    verbose_name = "utils"

    def ready(self):
        from django.contrib.admin import widgets

        # This allows models to be displayed in the admin forms via their display_with_pii property
        # instead of the default __str__ method when such property exists.
        widgets.Truncator = PIIAwareTruncator
        AdminReadonlyField.get_admin_url = pii_aware_get_admin_url
