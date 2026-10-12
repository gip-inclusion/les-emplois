from django.shortcuts import render
from django_datadog_logger.formatters.datadog import get_client_ip

from itou.utils.auth import check_user


@check_user(lambda user: user.is_superuser)
def headers(request):
    return render(request, "selftest/headers.html", {"request": request, "request_ip": get_client_ip(request)})
