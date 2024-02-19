from django.http.response import HttpResponse
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
        return get_response(request)

    return middleware
