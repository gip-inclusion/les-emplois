from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render
from django.views import debug
from django.views.decorators.cache import never_cache


def get_settings_list():
    """Build the list of (setting, value, is_default_value)."""
    # Code heavily inspired from django.core.management.commands.diffsettings
    current_settings = settings._wrapped.__dict__
    setting_cleanser = debug.SafeExceptionReporterFilter().cleanse_setting
    return [(k, setting_cleanser(k, v)) for k, v in sorted(current_settings.items()) if not k.startswith("_")]


@never_cache
@user_passes_test(lambda user: user.is_active and user.is_superuser)
def settings_list(request):
    context_data = {
        **admin.site.each_context(request),
        "setting_items": get_settings_list(),
    }
    return render(request, "settings/list.html", context_data)
