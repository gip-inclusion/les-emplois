from django.conf import settings
from django.http import HttpResponseForbidden


def settings_protected_view(setting_name):
    def decorator(view_func):
        def wrapper(request, *args, **kwargs):
            if getattr(settings, setting_name, False):
                return view_func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden("Access Denied")

        return wrapper

    return decorator
