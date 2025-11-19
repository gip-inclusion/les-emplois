from django.conf import settings
from django.http import Http404, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme

from itou.nexus.utils import generate_jwt
from itou.utils.urls import add_url_params


def auto_login(request):
    next_url = request.GET.get("next_url")

    if next_url is None or settings.NEXUS_AUTO_LOGIN_KEY is None:
        raise Http404

    if url_has_allowed_host_and_scheme(next_url, settings.NEXUS_ALLOWED_REDIRECT_HOSTS, require_https=True):
        return HttpResponseRedirect(add_url_params(next_url, {"auto_login": generate_jwt(request.user)}))

    raise Http404
