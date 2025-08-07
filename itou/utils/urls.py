from urllib.parse import SplitResult, parse_qsl, urlsplit

from django.conf import settings
from django.http import QueryDict
from django.utils.encoding import iri_to_uri
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.safestring import mark_safe

from itou.utils.constants import ITOU_HELP_CENTER_URL
from itou.utils.zendesk import serialize_zendesk_params


def get_safe_url(request, param_name=None, fallback_url=None, url=None):
    url = url or request.GET.get(param_name) or request.POST.get(param_name)

    allowed_hosts = settings.ALLOWED_HOSTS
    require_https = request.is_secure()

    if url:
        if settings.DEBUG:
            # In DEBUG mode the network location part `localhost:8000` contains
            # a port and fails the validation of `url_has_allowed_host_and_scheme`
            # since it's not a member of `allowed_hosts`:
            # https://github.com/django/django/blob/525274f/django/utils/http.py#L413
            # As a quick fix, we build a new URL without the port.

            url_info = urlsplit(url)
            url_to_check = SplitResult(
                scheme=url_info.scheme,
                netloc=url_info.hostname,
                path=url_info.path,
                query=url_info.query,
                fragment=url_info.fragment,
            ).geturl()
        else:
            url_to_check = url
        if url_has_allowed_host_and_scheme(url_to_check, allowed_hosts, require_https):
            return iri_to_uri(url)

    return fallback_url


def get_absolute_url(path=""):
    if path.startswith("/"):
        path = path[1:]
    return f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/{path}"


def get_external_link_markup(url, text):
    return mark_safe(
        f'<a href="{url}" rel="noopener" target="_blank" class="has-external-link" '
        f'aria-label="Ouverture dans un nouvel onglet">{text}</a>'
    )


def add_url_params(url: str, params: dict[str, str]) -> str:
    """Add GET params to provided URL being aware of existing.

    :param url: string of target URL
    :param params: dict containing requested params to be added
    :return: string with updated URL

    >> url = 'http://localhost:8000/login/activate_employer_account?next_url=%2Finvitations
    >> new_params = {'test': 'value' }
    >> add_url_params(url, new_params)
    'http://localhost:8000/login/activate_employer_account?next_url=%2Finvitations&test=value
    """

    # Remove params with None values
    params = {key: params[key] for key in params if params[key] is not None}
    try:
        url_parts = urlsplit(url)
    except ValueError:
        # URL is invalid so it's useless to continue.
        return None
    query = dict(parse_qsl(url_parts.query))
    query.update(params)

    new_url = url_parts._replace(query=urlencode(query)).geturl()

    return new_url


def get_url_param_value(url: str, key: str) -> str:
    """Get a parameter value from a provided URL.

    :param url: string of target URL
    :param key: key of the requested param
    :return: value of the requested param

    >> url = 'http://localhost:8000/?channel=map_conseiller
    >> key = "channel"
    >> get_url_param_value(url, key)
    'map_conseiller'
    """
    try:
        parsed_url = urlsplit(url)
    except ValueError:
        # URL is invalid so it's useless to continue.
        return None

    return QueryDict(parsed_url.query).get(key)


class SiretConverter:
    """
    Custom path converter for Siret.
    https://docs.djangoproject.com/en/dev/topics/http/urls/#registering-custom-path-converters
    """

    regex = "[0-9]{14}"

    def to_python(self, value):
        return int(value)

    def to_url(self, value):
        return f"{value}"


def get_tally_form_url(form_id, **kwargs):
    url = f"{settings.TALLY_URL}/r/{form_id}"

    if kwargs:
        url += "?" + urlencode(kwargs)

    return mark_safe(url)


def get_zendesk_form_url(request=None):
    url = f"{ITOU_HELP_CENTER_URL}/requests/new"

    if request and request.user and request.user.is_authenticated:
        url = add_url_params(url, serialize_zendesk_params(request))

    return url


def markdown_url_set_target_blank(attrs, new=False):
    attrs[(None, "target")] = "_blank"
    attrs[(None, "rel")] = "noopener"
    attrs[(None, "aria-label")] = "Ouverture dans un nouvel onglet"
    return attrs


def markdown_url_set_protocol(attrs, new=False):
    if href := attrs.get((None, "href")):
        if not (href.startswith("http") or href.startswith("mailto")):
            attrs[(None, "href")] = "https://" + href
    return attrs
