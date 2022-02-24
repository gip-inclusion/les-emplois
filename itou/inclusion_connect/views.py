import json
import logging
from urllib.parse import unquote

import httpx
from django.contrib import messages
from django.contrib.auth import login
from django.core import signing
from django.http import HttpResponseRedirect  # , JsonResponse
from django.urls import reverse
from django.utils import crypto
from django.utils.http import urlencode

from itou.utils.urls import get_absolute_url

from .constants import (  # INCLUSION_CONNECT_SCOPES,
    INCLUSION_CONNECT_CLIENT_ID,
    INCLUSION_CONNECT_CLIENT_SECRET,
    INCLUSION_CONNECT_ENDPOINT_AUTHORIZE,
    INCLUSION_CONNECT_ENDPOINT_TOKEN,
    INCLUSION_CONNECT_ENDPOINT_USERINFO,
    INCLUSION_CONNECT_SESSION_STATE,
    INCLUSION_CONNECT_SESSION_TOKEN,
)
from .models import InclusionConnectState, InclusionConnectUserData, create_or_update_user, userinfo_to_user_model_dict


logger = logging.getLogger(__name__)


def get_callback_redirect_uri(request) -> str:
    redirect_uri = get_absolute_url(reverse("inclusion_connect:callback"))
    next_url = request.GET.get("next")
    if next_url:
        redirect_uri += f"?next={next_url}"

    # The redirect_uri should be defined in the IC settings to be allowed
    # The integration platform allows "http://localhost:8080/callback" so an associated endpoint
    # should be set in itou.
    return redirect_uri


def state_new() -> str:
    # Generate CSRF and save the state for further verification
    signer = signing.Signer()
    csrf = crypto.get_random_string(length=12)
    csrf_signed = signer.sign(csrf)
    InclusionConnectState.objects.create(csrf=csrf)

    return csrf_signed


def state_is_valid(csrf_signed: str) -> bool:
    if not csrf_signed:
        return False

    signer = signing.Signer()
    try:
        csrf = signer.unsign(unquote(csrf_signed))
    except signing.BadSignature:
        return False

    # Cleanup old states if any
    InclusionConnectState.objects.cleanup()

    state = InclusionConnectState.objects.filter(csrf=csrf).first()
    if not state:
        return False

    # One-time use
    state.delete()

    return True


def inclusion_connect_authorize(request):
    redirect_uri = get_callback_redirect_uri(request)
    csrf_signed = state_new()
    data = {
        "response_type": "code",
        "client_id": INCLUSION_CONNECT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "openid",
        "state": csrf_signed,
        "nonce": crypto.get_random_string(length=12),
        "acr_values": "eidas1",
    }
    url = INCLUSION_CONNECT_ENDPOINT_AUTHORIZE
    return HttpResponseRedirect(f"{url}?{urlencode(data)}")


def inclusion_connect_callback(request):  # pylint: disable=too-many-return-statements
    code = request.GET.get("code")
    if code is None:
        messages.error(
            request, "Inclusion Connect n’a pas transmis le paramètre « code » nécessaire à votre authentification."
        )
        return HttpResponseRedirect(reverse("account_login"))

    state = request.GET.get("state")
    if not state_is_valid(state):
        message = (
            "Le paramètre « state » fourni par Inclusion Connect"
            " et nécessaire à votre authentification n’est pas valide."
        )
        messages.error(request, message)
        return HttpResponseRedirect(reverse("account_login"))

    redirect_uri = get_callback_redirect_uri(request)

    data = {
        "client_id": INCLUSION_CONNECT_CLIENT_ID,
        "client_secret": INCLUSION_CONNECT_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    # Exceptions catched by Sentry
    url = INCLUSION_CONNECT_ENDPOINT_TOKEN
    response = httpx.post(url, data=data, timeout=30)

    if response.status_code != 200:
        message = "Impossible d'obtenir le jeton d'Inclusion Connect."
        logger.error("%s : %s", message, response.content)
        messages.error(request, message)
        return HttpResponseRedirect(reverse("account_login"))

    # Contains access_token, token_type, expires_in, id_token
    token_data = response.json()

    access_token = token_data.get("access_token")
    if not access_token:
        message = "Aucun champ « access_token » dans la réponse Inclusion Connect, impossible de vous authentifier"
        messages.error(request, message)
        logger.error(message)
        return HttpResponseRedirect(reverse("account_login"))

    # A token has been provided so it's time to fetch associated user infos
    # because the token is only valid for 5 seconds.
    url = INCLUSION_CONNECT_ENDPOINT_USERINFO
    response = httpx.get(
        url,
        params={"schema": "openid"},
        headers={"Authorization": "Bearer " + access_token},
        timeout=60,
    )
    if response.status_code != 200:
        message = "Impossible d'obtenir les informations utilisateur d'Inclusion Connect."
        logger.error(message)
        return HttpResponseRedirect(reverse("account_login"))

    try:
        user_data = json.loads(response.content.decode("utf-8"))
    except json.decoder.JSONDecodeError:
        message = "Impossible de décoder les informations utilisateur."
        logger.error(message)
        return HttpResponseRedirect(reverse("account_login"))

    if "sub" not in user_data:
        # 'sub' is the unique identifier from Inclusion Connect, we need that to match a user later on.
        message = "Le paramètre « sub » n'a pas été retourné par InclusionConnect. Il est nécessaire pour identifier un utilisateur."  # noqa E501
        logger.error(message)
        return HttpResponseRedirect(reverse("account_login"))

    # email_verified = user_data.get("email_verified")
    # TODO: error is email_verified is False
    ic_user_data = InclusionConnectUserData(**userinfo_to_user_model_dict(user_data))

    # Keep token_data["id_token"] to logout from FC
    # At this step, we can update the user's fields in DB and create a session if required
    user, created = create_or_update_user(ic_user_data)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session[INCLUSION_CONNECT_SESSION_TOKEN] = token_data["id_token"]
    request.session[INCLUSION_CONNECT_SESSION_STATE] = state
    request.session.modified = True

    next_url = reverse("dashboard:index")
    return HttpResponseRedirect(next_url)

def inclusion_connect_logout(request):
    # The user can be authenticated on IC w/o a session on itou.
    id_token = request.GET.get("id_token")
    state = request.GET.get("state", "")
