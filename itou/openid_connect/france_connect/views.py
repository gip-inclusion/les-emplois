import json
import logging

import httpx
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils import crypto
from django.utils.http import urlencode

from itou.openid_connect.errors import redirect_with_error_sso_email_conflict_on_registration
from itou.openid_connect.france_connect import constants
from itou.openid_connect.france_connect.models import FranceConnectState, FranceConnectUserData
from itou.openid_connect.models import (
    EmailInUseException,
    InvalidKindException,
    MultipleSubSameEmailException,
    MultipleUsersFoundException,
)
from itou.openid_connect.utils import init_user_nir_from_session
from itou.users.enums import IdentityProvider, UserKind
from itou.utils import constants as global_constants
from itou.utils.urls import get_absolute_url


logger = logging.getLogger(__name__)


def _redirect_to_job_seeker_login_on_error(error_msg, request, extra_tags=""):
    messages.error(request, error_msg, extra_tags)
    return HttpResponseRedirect(reverse("login:job_seeker"))


@login_not_required
def france_connect_authorize(request):
    # The redirect_uri should be defined in the FC settings to be allowed
    # NB: the integration platform allows "http://127.0.0.1:8000/franceconnect/callback"
    redirect_uri = get_absolute_url(reverse("france_connect:callback"))
    state = FranceConnectState.save_state()
    data = {
        "response_type": "code",
        "client_id": settings.FRANCE_CONNECT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": constants.FRANCE_CONNECT_SCOPES,
        "state": state,
        "nonce": crypto.get_random_string(length=32),
        "acr_values": "eidas1",
    }
    url = constants.FRANCE_CONNECT_ENDPOINT_AUTHORIZE
    return HttpResponseRedirect(f"{url}?{urlencode(data)}")


@login_not_required
def france_connect_callback(request):
    state = request.GET.get("state")
    fc_state = FranceConnectState.get_from_state(state)
    if not fc_state or not fc_state.is_valid():
        error_msg = (
            "Le paramètre « state » fourni par FranceConnect et nécessaire à votre authentification n’est pas valide."
        )
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    code = request.GET.get("code")
    if code is None:
        error = request.GET.get("error")
        log = logger.info
        match error:
            case None:
                error_msg = "FranceConnect n’a pas transmis le paramètre « code » nécessaire à votre authentification."
            case "access_denied":
                error_msg = "Votre connexion à FranceConnect a échoué. Veuillez réessayer."
            case "server_error" | "temporarily_unavailable":
                error_msg = "FranceConnect est temporairement indisponible. Veuillez réessayer ultérieurement."
            case _:
                # "invalid_scope", "invalid_request" or any other unexpected error:
                # we either need to fix our settings or add the new error to the match case.
                error_msg = (
                    "La connexion avec FranceConnect est actuellement impossible. "
                    "Veuillez utiliser un autre mode de connexion."
                )
                log = logger.error
        log(
            "FranceConnect callback with state=%s - code=%s - error=%s - error_description=%s",
            state,
            code,
            error,
            request.GET.get("error_description"),
        )
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    redirect_uri = get_absolute_url(reverse("france_connect:callback"))
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
        logger.error("FranceConnect token request failed with status %s", response.status_code)
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    # Contains access_token, token_type, expires_in, id_token
    token_data = response.json()

    access_token = token_data.get("access_token")
    if not access_token:
        error_msg = "Aucun champ « access_token » dans la réponse FranceConnect, impossible de vous authentifier"
        logger.error("FranceConnect token request returned no access token")
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
        logger.error("FranceConnect userinfo request failed with status %s", response.status_code)
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    try:
        user_data = json.loads(response.content)
    except json.decoder.JSONDecodeError:
        error_msg = "Impossible de décoder les informations utilisateur."
        logger.error("FranceConnect userinfo response is not a valid JSON")
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    if "sub" not in user_data:
        # 'sub' is the unique identifier from FranceConnect, we need that to match a user later on
        error_msg = "Le paramètre « sub » n'a pas été retourné par FranceConnect. Il est nécessaire pour identifier un utilisateur."  # noqa E501
        logger.error("FranceConnect userinfo response has no 'sub' field")
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    fc_user_data = FranceConnectUserData.from_user_info(user_data)

    try:
        # At this step, we can update the user's fields in DB and create a session if required
        user, _ = fc_user_data.create_or_update_user()
    except InvalidKindException as e:
        messages.info(request, "Ce compte existe déjà, veuillez vous connecter.")
        logger.info("FranceConnect login attempt with invalid user kind: %s", e.user.kind)
        return HttpResponseRedirect(UserKind.get_login_url(e.user.kind))
    except MultipleSubSameEmailException as e:
        logger.info("FranceConnect multiple subs with same email")
        return _redirect_to_job_seeker_login_on_error(
            e.format_message_html(IdentityProvider.FRANCE_CONNECT), request=request
        )
    except EmailInUseException as e:
        logger.info("User should be using another login method")
        return redirect_with_error_sso_email_conflict_on_registration(
            request, e.user, IdentityProvider.FRANCE_CONNECT.label
        )
    except MultipleUsersFoundException as e:
        logger.info("Email conflict detected")
        return _redirect_to_job_seeker_login_on_error(
            "Vous avez deux comptes sur la plateforme et nous détectons un conflit d'email : "
            f"{e.users[0].email} et {e.users[1].email}. "
            "Veuillez vous rapprocher du support pour débloquer la situation en suivant "
            f"<a href='{global_constants.ITOU_HELP_CENTER_URL}'>ce lien</a>.",
            request=request,
        )

    init_user_nir_from_session(request, user)

    # Because we have more than one Authentication backend in our settings, we need to specify
    # the one we want to use in login
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    # Keep token_data["id_token"] to logout from FC
    request.session[constants.FRANCE_CONNECT_SESSION_TOKEN] = token_data["id_token"]
    request.session[constants.FRANCE_CONNECT_SESSION_STATE] = state
    request.session.modified = True

    next_url = reverse("dashboard:index")
    return HttpResponseRedirect(next_url)


@login_not_required
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
