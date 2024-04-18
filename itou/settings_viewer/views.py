from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render
from django.views import debug
from django.views.decorators.cache import never_cache


IGNORE_SET = {
    # Cleanup most keys in Django 5
    "DEFAULT_FILE_STORAGE",
    "STATICFILES_STORAGE",
    "USE_L10N",
}


def get_settings_list():
    # Code heavily inspired from django.core.management.commands.diffsettings
    setting_cleanser = debug.SafeExceptionReporterFilter().cleanse_setting
    return [
        (k, setting_cleanser(k, getattr(settings, k)))
        for k in sorted(dir(settings))
        if not k.startswith("_") and k not in IGNORE_SET
    ]


@never_cache
@user_passes_test(lambda user: user.is_active and user.is_superuser)
def settings_list(request):
    context_data = {
        **admin.site.each_context(request),
        "setting_items": get_settings_list(),
        "title": "Settings values",
        "subtitle": None,
    }
    return render(request, "settings/list.html", context_data)
