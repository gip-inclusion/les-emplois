from math import ceil

import sentry_sdk
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import connection
from django.http import HttpResponseRedirect, JsonResponse, QueryDict
from django.http.response import HttpResponse, HttpResponseServerError
from django.shortcuts import render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers

from itou.utils.throttling import FailSafeAnonRateThrottle, FailSafeUserRateThrottle
from itou.www.constants import REDIRECTED_FROM_OLD_DOMAIN_QUERY_PARAM


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
        if getattr(settings, "BYPASS_TERMS_ACCEPTANCE", False):
            return None  # setting to globally disable this check
        if not getattr(view_func, "login_required", True):
            return None  # don't enforce terms acceptance for public endpoints
        if not request.user.is_authenticated or not request.user.must_accept_terms:
            return None
        if request.method == "POST" or request.htmx:
            return None  # avoid a brutal redirection for HTMX requests or form submissions
        if request.path.startswith("/accounts/"):
            return None
        if not (match := getattr(request, "resolver_match", None)):
            return None
        top_level_namespace = match.namespaces[0] if match.namespaces else ""
        if top_level_namespace in [
            "logout",
            "itou.api",
            # Anyway, this should be only reachable by superusers and staff members... But we don't want
            # professionals reaching these endpoints to first accept the terms and then get a 403/404
            "admin",
            "itou_staff_views",
            "otp_views",
        ]:
            return None
        if getattr(view_func, "_bypass_terms_acceptance", False):  # views can be decorated to be exempt from the check
            return None
        url = reverse("legal-terms", query={"next": request.get_full_path()})
        return HttpResponseRedirect(url)


class RedirectToNewDomainMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        url = _get_redirect_url(request)
        if url is None:
            return None
        return HttpResponseRedirect(url)


def _get_redirect_url(request):
    if not settings.REDIRECT_TO_NEW_DOMAIN:
        return None
    if request.get_host() == settings.NEW_DOMAIN:
        return None
    if request.path.startswith("/api/"):
        # Clients of our API may not handle redirections. Let them
        # some time before redirecting (or maybe never redirect
        # them if we still see calls to the old domain in logs).
        return None
    if request.path.startswith(reverse("otp_views:verify_otp")):
        # Don't redirect to the new domain, otherwise the user will
        # end up at "new.domain/otp/verify" and it will look like the
        # user has been disconnected (which they are not).
        return None
    if request.method != "GET":
        # Don't redirect POST, DELETE, etc.: if the user visits the
        # old domain _before_ we enable the redirection for them, then
        # POST data and we redirect them to the new domain where they
        # never authenticated, they will lose data.
        # FIXME (dbaty, 2026-08-20): remove this once all users
        # are redirected to the new domain (see `if block below).
        return None
    user = request.user
    if not (user and user.is_authenticated and user.is_staff):
        # For now, redirect only staff users. We'll expand to
        # other users once we're sure that everything is fine.
        return None

    query = QueryDict(request.GET.urlencode(), mutable=True)
    query[REDIRECTED_FROM_OLD_DOMAIN_QUERY_PARAM] = "1"
    return f"https://{settings.NEW_DOMAIN}{request.path}?{query.urlencode()}"
