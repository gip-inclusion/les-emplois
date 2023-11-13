import json
import logging

import httpx
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils import crypto
from django.utils.http import urlencode

from itou.users.enums import UserKind
from itou.utils import constants as global_constants
from itou.utils.urls import get_absolute_url

from ..models import InvalidKindException, MultipleUsersFoundException
from . import constants
from .models import FranceConnectState, FranceConnectUserData


logger = logging.getLogger(__name__)


def _redirect_to_job_seeker_login_on_error(error_msg, request=None):
    if request:
        messages.error(request, error_msg)
    return HttpResponseRedirect(reverse("login:job_seeker"))


def get_callback_redirect_uri(request) -> str:
    redirect_uri = get_absolute_url(reverse("france_connect:callback"))
    next_url = request.GET.get("next")
    if next_url:
        redirect_uri += f"?next={next_url}"

    # The redirect_uri should be defined in the FC settings to be allowed
    # NB: the integration platform allows "http://127.0.0.1:8000/franceconnect/callback"
    return redirect_uri


def france_connect_authorize(request):
    redirect_uri = get_callback_redirect_uri(request)
    state = FranceConnectState.save_state()
    data = {
        "response_type": "code",
        "client_id": settings.FRANCE_CONNECT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": constants.FRANCE_CONNECT_SCOPES,
        "state": state,
        "nonce": crypto.get_random_string(length=12),
        "acr_values": "eidas1",
    }
    url = constants.FRANCE_CONNECT_ENDPOINT_AUTHORIZE
    return HttpResponseRedirect(f"{url}?{urlencode(data)}")


def france_connect_callback(request):
    code = request.GET.get("code")
    if code is None:
        error_msg = ("France Connect n’a pas transmis le paramètre « code » nécessaire à votre authentification.",)
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    state = request.GET.get("state")
    fc_state = FranceConnectState.get_from_state(state)
    if not fc_state or not fc_state.is_valid():
        error_msg = (
            "Le paramètre « state » fourni par France Connect et nécessaire à votre authentification n’est pas valide."
        )
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    redirect_uri = get_callback_redirect_uri(request)

    data = {
        "client_id": settings.FRANCE_CONNECT_CLIENT_ID,
        "client_secret": settings.FRANCE_CONNECT_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    # Exceptions catched by Sentry
    url = constants.FRANCE_CONNECT_ENDPOINT_TOKEN
    response = httpx.post(url, data=data, timeout=30)

    if response.status_code != 200:
        error_msg = "Impossible d'obtenir le jeton de FranceConnect."
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    # Contains access_token, token_type, expires_in, id_token
    token_data = response.json()

    access_token = token_data.get("access_token")
    if not access_token:
        error_msg = "Aucun champ « access_token » dans la réponse FranceConnect, impossible de vous authentifier"
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    # A token has been provided so it's time to fetch associated user infos
    # because the token is only valid for 5 seconds.
    url = constants.FRANCE_CONNECT_ENDPOINT_USERINFO

    response = httpx.get(
        url,
        params={"schema": "openid"},
        headers={"Authorization": "Bearer " + access_token},
        timeout=60,
    )
    if response.status_code != 200:
        error_msg = "Impossible d'obtenir les informations utilisateur de FranceConnect."
        return _redirect_to_job_seeker_login_on_error(error_msg)

    try:
        user_data = json.loads(response.content.decode("utf-8"))
    except json.decoder.JSONDecodeError:
        error_msg = "Impossible de décoder les informations utilisateur."
        return _redirect_to_job_seeker_login_on_error(error_msg)

    if "sub" not in user_data:
        # 'sub' is the unique identifier from France Connect, we need that to match a user later on
        error_msg = "Le paramètre « sub » n'a pas été retourné par FranceConnect. Il est nécessaire pour identifier un utilisateur."  # noqa E501
        logger.error(error_msg)
        return _redirect_to_job_seeker_login_on_error(error_msg)

    fc_user_data = FranceConnectUserData.from_user_info(user_data)

    try:
        # At this step, we can update the user's fields in DB and create a session if required
        user, _ = fc_user_data.create_or_update_user()
    except InvalidKindException as e:
        messages.info(request, "Ce compte existe déjà, veuillez vous connecter.")
        url = {
            UserKind.PRESCRIBER: reverse("login:prescriber"),
            UserKind.EMPLOYER: reverse("login:employer"),
            UserKind.LABOR_INSPECTOR: reverse("login:labor_inspector"),
        }[e.user.kind]
        return HttpResponseRedirect(url)
    except MultipleUsersFoundException as e:
        return _redirect_to_job_seeker_login_on_error(
            "Vous avez deux comptes sur la plateforme et nous détectons un conflit d'email : "
            f"{e.users[0].email} et {e.users[1].email}. "
            "Veuillez vous rapprocher du support pour débloquer la situation en suivant "
            f"<a href='{global_constants.ITOU_HELP_CENTER_URL}'>ce lien</a>.",
            request=request,
        )

    nir = request.session.get(global_constants.ITOU_SESSION_NIR_KEY)
    if nir:
        user.nir = nir
        user.lack_of_nir_reason = ""
        user.save(update_fields=["nir", "lack_of_nir_reason"])

    # Because we have more than one Authentication backend in our settings, we need to specify
    # the one we want to use in login
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    # Keep token_data["id_token"] to logout from FC
    request.session[constants.FRANCE_CONNECT_SESSION_TOKEN] = token_data["id_token"]
    request.session[constants.FRANCE_CONNECT_SESSION_STATE] = state
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
        "post_logout_redirect_uri": get_absolute_url(reverse("search:employers_home")),
    }
    url = constants.FRANCE_CONNECT_ENDPOINT_LOGOUT
    complete_url = f"{url}?{urlencode(params)}"
    return HttpResponseRedirect(complete_url)
