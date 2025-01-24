from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.utils.http import url_has_allowed_host_and_scheme


def add_query_params(url, params):
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    query_params.update(params)
    encoded_query = urlencode(query_params, doseq=True)
    new_url = urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            encoded_query,
            parsed_url.fragment,
        )
    )
    return new_url


# TODO(calum): Replace usage with get_safe_url from itou.utils
def is_safe_url(request, url):
    # get_host already validates the given host, so no need to check it again
    allowed_hosts = {request.get_host()} | set(settings.ALLOWED_HOSTS)

    if "*" in allowed_hosts:
        parsed_host = urlparse(url).netloc
        allowed_host = {parsed_host} if parsed_host else None
        return url_has_allowed_host_and_scheme(url, allowed_hosts=allowed_host)

    return url_has_allowed_host_and_scheme(url, allowed_hosts=allowed_hosts)


def get_request_param(request, param, default=None):
    if request is None:
        return default
    return request.POST.get(param) or request.GET.get(param, default)


def get_next_redirect_url(request, redirect_field_name=REDIRECT_FIELD_NAME) -> str | None:
    """
    Returns the next URL to redirect to, if it was explicitly passed
    via the request.
    """
    redirect_to = get_request_param(request, redirect_field_name)
    if redirect_to and not is_safe_url(request, redirect_to):
        redirect_to = None
    return redirect_to


def passthrough_next_redirect_url(request, url, redirect_field_name):
    next_url = get_next_redirect_url(request, redirect_field_name)
    if next_url:
        url = add_query_params(url, {redirect_field_name: next_url})
    return url


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


def get_http_user_agent(request):
    return request.META.get("HTTP_USER_AGENT", "Unspecified")
