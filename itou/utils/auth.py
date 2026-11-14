import os
import re
from functools import wraps

from allauth.core.internal.httpkit import clean_client_ip
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest


RE_LIST_SPLIT = re.compile(r"[\s,]")
CC_REVERSE_PROXY_IPS = {ip for ip in RE_LIST_SPLIT.split(os.getenv("CC_REVERSE_PROXY_IPS", "")) if ip}


def get_client_ip_from_xff(request: HttpRequest) -> str | None:
    """Returns client IP from X-Forwarded-For excluding trusted proxy list.

    Quoting https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/X-Forwarded-For:

    > The IPs or IP ranges of the trusted reverse proxies are
    > configured. The X-Forwarded-For IP list is searched from the
    > rightmost, skipping all addresses that are on the trusted proxy
    > list. The first non-matching address is the target address.
    """
    xff = [ip for ip in RE_LIST_SPLIT.split(request.headers.get("x-forwarded-for", "")) if ip]
    for ip in reversed(xff):
        if ip not in CC_REVERSE_PROXY_IPS:
            return ip
    return None


def get_client_ip(request: HttpRequest) -> str | None:
    """Get the client IP address according to Clever Cloud list of reverse proxies."""
    if ip := get_client_ip_from_xff(request):
        return clean_client_ip(ip)
    if ip := request.META.get("REMOTE_ADDR"):
        return clean_client_ip(ip)
    return None


def check_user(test_func, err_msg=""):
    def decorator(view_func):
        def _check_user_view_wrapper(request, *args, **kwargs):
            test_pass = test_func(request.user)

            if test_pass:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied(err_msg)

        return wraps(view_func)(_check_user_view_wrapper)

    return decorator


def check_user_or_404(test_func, err_msg=""):
    """Same as `check_user`, but hides the existence of the view instead of denying access."""

    def decorator(view_func):
        def _check_user_view_wrapper(request, *args, **kwargs):
            test_pass = test_func(request.user)

            if test_pass:
                return view_func(request, *args, **kwargs)
            raise Http404(err_msg)

        return wraps(view_func)(_check_user_view_wrapper)

    return decorator


def check_request(test_func, err_msg=""):
    def decorator(view_func):
        def _check_request_view_wrapper(request, *args, **kwargs):
            test_pass = test_func(request)

            if test_pass:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied(err_msg)

        return wraps(view_func)(_check_request_view_wrapper)

    return decorator


class LoginNotRequiredMixin:
    @classmethod
    def as_view(cls, *args, **kwargs):
        view = super().as_view(*args, **kwargs)
        return login_not_required(view)
