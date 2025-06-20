from math import ceil

import sentry_sdk
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import connection
from django.http import JsonResponse
from django.http.response import HttpResponse, HttpResponseServerError
from django.shortcuts import render
from django.utils.cache import add_never_cache_headers

from itou.utils.throttling import FailSafeUserRateThrottle


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
        if request.user.is_authenticated and getattr(view_func, "login_required", True):
            throttler = FailSafeUserRateThrottle()
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
