import os

from django.conf import settings as _all_settings_do_not_use_all_of_it
from django.shortcuts import render

from itou.utils.auth import check_user, get_client_ip


@check_user(lambda user: user.is_superuser)
def headers(request):
    return render(
        request,
        "selftest/headers.html",
        {
            "request": request,
            "CC_REVERSE_PROXY_IPS": os.getenv("CC_REVERSE_PROXY_IPS"),
            "request_ip": get_client_ip(request),
        },
    )


@check_user(lambda user: user.is_superuser)
def settings(request):
    settings = {
        key: getattr(_all_settings_do_not_use_all_of_it, key)
        for key in [
            "WEB_SERVER_MODE",
            "REQUIRE_MFA_ON_COMPANY_IDS",
            "REQUIRE_MFA_ON_ORGANIZATION_IDS",
        ]
    }

    return render(request, "selftest/settings.html", {"settings": settings})
