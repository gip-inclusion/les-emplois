from math import ceil

import sentry_sdk
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import connection
from django.http import HttpResponseRedirect, JsonResponse
from django.http.response import HttpResponse, HttpResponseServerError
from django.shortcuts import render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from itoutils.urls import add_url_params

from itou.utils.throttling import FailSafeAnonRateThrottle, FailSafeUserRateThrottle


def never_cache(get_response):
    def middleware(request):
        response = get_response(request)
        if request.user.is_authenticated:
            add_never_cache_headers(response)
        return response

    return middleware


class RateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Django REST Framework handles the rate limiting on the API.
        if "itou.api" not in request.resolver_match.app_names:
            throttler = FailSafeUserRateThrottle() if request.user.is_authenticated else FailSafeAnonRateThrottle()
            if not throttler.allow_request(request, None):
                retry_after = throttler.wait()
                if retry_after is not None:
                    retry_after = f"{ceil(retry_after)} secondes"
                return render(request, "429.html", context={"retry_after": retry_after}, status=429)
        return None


def public_health_check(get_response):
    def middleware(request):
        """
        Bypass ALLOWED_HOSTS checks

        CleverCloud probes access this path through IP directly, we don’t want to serve
        a 400 BadRequest because the request Host header is not in the ALLOWED_HOSTS.
        """
        if request.path == "/check-health":
            body = b"Healthy\n"
            ok_response = HttpResponse(
                body,
                content_type="text/plain",
                charset="utf-8",
                # CommonMiddleware is later in the middleware chain, and it checks ALLOWED_HOSTS.
                headers={
                    "Content-Length": str(len(body)),
                },
            )
            if settings.MAINTENANCE_MODE is True:
                return ok_response

            try:
                with connection.cursor() as c:
                    c.execute("SELECT 'check-database-connection'")
                cache.get("check-cache-connection")
                default_storage.exists("check-s3-file-access.txt")
                return ok_response
            except Exception as e:
                sentry_sdk.capture_exception(e)
                return HttpResponseServerError()
        return get_response(request)

    return middleware


def maintenance(get_response):
    def middleware(request):
        if settings.MAINTENANCE_MODE is True:
            if request.content_type == "application/json":
                return JsonResponse({"error": settings.MAINTENANCE_DESCRIPTION or "maintenance en cours"}, status=503)
            request.user = AnonymousUser()  # for itou.utils.context_processors.matomo
            return render(
                request, "static/maintenance.html", context={"description": settings.MAINTENANCE_DESCRIPTION}
            )
        return get_response(request)

    return middleware


class TermsAcceptanceMiddleware:
    """Middleware to ensure that professionals have accepted the latest terms before accessing the app."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        requires_login = getattr(view_func, "login_required", True)
        if not requires_login:
            return None  # don't enforce terms acceptance for public endpoints
        if not request.user.is_authenticated or not request.user.must_accept_terms():
            return None
        path = request.path
        match = request.resolver_match
        namespace = (match.namespace or "") if match else ""
        allowed_paths = {  # "Mon espace" must stay accessible
            reverse("dashboard:edit_user_email"),
            reverse("dashboard:edit_user_info"),
            reverse("dashboard:edit_user_notifications"),
        }
        allowed_prefixes = ["/accounts/"]
        allowed_namespaces = [
            "admin",  # anyway, should be unreachable by superusers
            "hijack",
            "invitations_views",
            "login",  # redundant... Except for the VerifyOTPView
            "logout",
            "signup",
            "itou_staff_views",  # anyway, should be unreachable by staff members
        ]
        if (
            any(path.startswith(prefix) for prefix in allowed_prefixes)
            or path in allowed_paths
            or namespace in allowed_namespaces
        ):
            return None
        url = add_url_params(reverse("legal-terms"), {REDIRECT_FIELD_NAME: request.get_full_path()})
        return HttpResponseRedirect(url)
