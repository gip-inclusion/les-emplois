import sentry_sdk
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import connection
from django.http.response import HttpResponse, HttpResponseServerError
from django.utils.cache import add_never_cache_headers


def never_cache(get_response):
    def middleware(request):
        response = get_response(request)
        if request.user.is_authenticated:
            add_never_cache_headers(response)
        return response

    return middleware


def public_health_check(get_response):
    def middleware(request):
        """
        Bypass ALLOWED_HOSTS checks

        CleverCloud probes access this path through IP directly, we don’t want to serve
        a 400 BadRequest because the request Host header is not in the ALLOWED_HOSTS.
        """
        if request.path == "/check-health":
            try:
                with connection.cursor() as c:
                    c.execute("SELECT 'check-database-connection'")
                cache.get("check-cache-connection")
                default_storage.exists("check-s3-file-access.txt")
                body = b"Healthy\n"
                return HttpResponse(
                    body,
                    content_type="text/plain",
                    charset="utf-8",
                    # CommonMiddleware is later in the middleware chain, and it checks ALLOWED_HOSTS.
                    headers={
                        "Content-Length": str(len(body)),
                    },
                )
            except Exception as e:
                sentry_sdk.capture_exception(e)
                return HttpResponseServerError()
        return get_response(request)

    return middleware
