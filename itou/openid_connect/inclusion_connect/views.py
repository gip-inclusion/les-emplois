import logging

from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.http import urlencode

from itou.utils.urls import get_absolute_url

from . import constants
from .client import client


logger = logging.getLogger(__name__)


def inclusion_connect_authorize(request):
    if not request.GET.get("user_kind"):
        raise KeyError("User kind missing.")
    return client.authorize(request)


def inclusion_connect_callback(request):  # pylint: disable=too-many-return-statements
    return client.callback(request)


def inclusion_connect_logout(request):
    token = request.GET.get("token")
    state = request.GET.get("state")
    post_logout_redirect_url = request.GET.get("redirect_url", reverse("home:hp"))

    # Fallback on session data.
    if not token:
        ic_session = request.session.get(constants.INCLUSION_CONNECT_SESSION_KEY)
        if not ic_session:
            raise KeyError("Missing session key.")
        token = ic_session["token"]
        state = ic_session["state"]

    params = {
        "id_token_hint": token,
        "state": state,
        "post_logout_redirect_uri": get_absolute_url(post_logout_redirect_url),
    }
    complete_url = f"{constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT}?{urlencode(params)}"
    return HttpResponseRedirect(complete_url)
