import json
import logging
from urllib.parse import unquote

import httpx
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.core import signing
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils import crypto
from django.utils.http import urlencode

from itou.utils.urls import get_absolute_url

from . import models as france_connect_models


logger = logging.getLogger(__name__)


def get_callback_redirect_uri(request) -> str:
    redirect_uri = get_absolute_url(reverse("france_connect:callback"))
    next_url = request.GET.get("next")
    if next_url:
        redirect_uri += f"?next={next_url}"

    # The redirect_uri should be defined in the FC settings to be allowed
    # The integration platform allows "http://localhost:8080/callback" so an associated endpoint
    # should be set in itou.
    return redirect_uri


def state_new() -> str:
    # Generate CSRF and save the state for further verification
    signer = signing.Signer()
    csrf = crypto.get_random_string(length=12)
    csrf_signed = signer.sign(csrf)
    france_connect_models.FranceConnectState.objects.create(csrf=csrf)

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
    france_connect_models.FranceConnectState.objects.cleanup()

    france_connect_state = france_connect_models.FranceConnectState.objects.filter(csrf=csrf).first()
    if not france_connect_state:
        return False

    # One-time use
    france_connect_state.delete()

    return True


def france_connect_authorize(request):
    redirect_uri = get_callback_redirect_uri(request)
    csrf_signed = state_new()
    data = {
        "response_type": "code",
        "client_id": settings.FRANCE_CONNECT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": settings.FRANCE_CONNECT_SCOPES,
        "state": csrf_signed,
        "nonce": crypto.get_random_string(length=12),
        "acr_values": "eidas1",
    }
    url = settings.FRANCE_CONNECT_URL + settings.FRANCE_CONNECT_ENDPOINT_AUTHORIZE
    return HttpResponseRedirect(f"{url}?{urlencode(data)}")


def france_connect_callback(request):  # pylint: disable=too-many-return-statements
    code = request.GET.get("code")
    if code is None:
        messages.error(
            request, "France Connect n’a pas transmis le paramètre « code » nécessaire à votre authentification."
        )
        return HttpResponseRedirect(reverse("account_login"))

    state = request.GET.get("state")
    if not state_is_valid(state):
        message = (
            "Le paramètre « state » fourni par France Connect et nécessaire à votre authentification n’est pas valide."
        )
        messages.error(request, message)
        return HttpResponseRedirect(reverse("account_login"))

    redirect_uri = get_callback_redirect_uri(request)

    data = {
        "client_id": settings.FRANCE_CONNECT_CLIENT_ID,
        "client_secret": settings.FRANCE_CONNECT_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    # Exceptions catched by Sentry
    url = settings.FRANCE_CONNECT_URL + settings.FRANCE_CONNECT_ENDPOINT_TOKEN
    response = httpx.post(url, data=data, timeout=30)

    if response.status_code != 200:
        message = "Impossible d'obtenir le jeton de FranceConnect."
        logger.error("%s : %s", message, response.content)
        messages.error(request, message)
        return HttpResponseRedirect(reverse("account_login"))

    # Contains access_token, token_type, expires_in, id_token
    token_data = response.json()

    access_token = token_data.get("access_token")
    if not access_token:
        message = "Aucun champ « access_token » dans la réponse FranceConnect, impossible de vous authentifier"
        messages.error(request, message)
        logger.error(message)
        return HttpResponseRedirect(reverse("account_login"))

    # A token has been provided so it's time to fetch associated user infos
    # because the token is only valid for 5 seconds.
    url = settings.FRANCE_CONNECT_URL + settings.FRANCE_CONNECT_ENDPOINT_USERINFO
    response = httpx.get(
        url,
        params={"schema": "openid"},
        headers={"Authorization": "Bearer " + access_token},
        timeout=60,
    )
    if response.status_code != 200:
        message = "Impossible d'obtenir les informations utilisateur de FranceConnect."
        logger.error(message)
        return HttpResponseRedirect(reverse("account_login"))

    try:
        user_data = json.loads(response.content.decode("utf-8"))
    except json.decoder.JSONDecodeError:
        message = "Impossible de décoder les informations utilisateur."
        logger.error(message)
        return HttpResponseRedirect(reverse("account_login"))

    if "sub" not in user_data:
        message = "Le paramètre « sub » n'a pas été retourné par FranceConnect."
        logger.error(message)
        return HttpResponseRedirect(reverse("account_login"))

    fc_user_data = france_connect_models.FranceConnectUserData(**france_connect_models.load_user_data(user_data))

    # Keep token_data["id_token"] to logout from FC
    # At this step, we can update the user's fields in DB and create a session if required
    user, created = france_connect_models.create_or_update_user(fc_user_data)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session["franceconnect_id_token"] = token_data["id_token"]
    request.session["franceconnect_state"] = state
    request.session.modified = True

    next_url = reverse("dashboard:index")
    return HttpResponseRedirect(next_url)


def france_connect_logout(request):
    # The user can be authentified on FC w/o a session on itou.
    # https://partenaires.franceconnect.gouv.fr/fcp/fournisseur-service#sign_out
    id_token = request.GET.get("id_token")
    state = request.GET.get("state", "")

    if not id_token:
        return JsonResponse({"message": "Le paramètre « id_token » est manquant."}, status=400)

    params = {
        "id_token_hint": id_token,
        "state": state,
        "post_logout_redirect_uri": get_absolute_url(reverse("home:hp")),
    }
    url = settings.FRANCE_CONNECT_URL + settings.FRANCE_CONNECT_ENDPOINT_LOGOUT
    complete_url = f"{url}?{urlencode(params)}"
    return HttpResponseRedirect(complete_url)
