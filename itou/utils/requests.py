from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django.contrib.auth import REDIRECT_FIELD_NAME

from itou.utils.urls import get_safe_url


# TODO: review how often the following params are actually passed in POST, if ever
# If they're not used, delete the usages and these functions
# LogoutView : self.redirect_field_name


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
    if redirect_to and get_safe_url(request, url=redirect_to) is None:
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
