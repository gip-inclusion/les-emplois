import json
import logging

import httpx
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import crypto
from django.utils.http import urlencode

from itou.external_data.models import ExternalDataImport
from itou.external_data.tasks import huey_import_user_pe_data
from itou.users.enums import UserKind
from itou.utils import constants as global_constants
from itou.utils.urls import add_url_params, get_absolute_url

from ..models import InvalidKindException, MultipleUsersFoundException
from . import constants
from .models import PoleEmploiConnectState, PoleEmploiConnectUserData


logger = logging.getLogger(__name__)


def _redirect_to_job_seeker_login_on_error(error_msg, request=None):
    if request:
        messages.error(request, error_msg)
    return HttpResponseRedirect(reverse("login:job_seeker"))


def pe_connect_authorize(request):
    # The redirect_uri should be defined in the PEAMU settings to be allowed
    # NB: the integration platform allows "http://127.0.0.1:8000/pe_connect/callback"
    redirect_uri = get_absolute_url(reverse("pe_connect:callback"))
    state = PoleEmploiConnectState.save_state()
    data = {
        "response_type": "code",
        "client_id": settings.API_ESD["KEY"],
        "redirect_uri": redirect_uri,
        "scope": constants.PE_CONNECT_SCOPES,
        "state": state,
        "nonce": crypto.get_random_string(length=12),
        "realm": "/individu",  # PEAMU specificity
    }
    url = constants.PE_CONNECT_ENDPOINT_AUTHORIZE
    return HttpResponseRedirect(f"{url}?{urlencode(data)}")


def pe_connect_callback(request):
    code = request.GET.get("code")
    if code is None:
        error_msg = "PôleEmploiConnect n’a pas transmis le paramètre « code » nécessaire à votre authentification."
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    state = request.GET.get("state")
    pe_state = PoleEmploiConnectState.get_from_state(state)
    if not pe_state or not pe_state.is_valid():
        error_msg = (
            "Le paramètre « state » fourni par PôleEmploiConnect et nécessaire à votre authentification "
            "n’est pas valide."
        )
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    redirect_uri = get_absolute_url(reverse("pe_connect:callback"))

    data = {
        "client_id": settings.API_ESD["KEY"],
        "client_secret": settings.API_ESD["SECRET"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    url = add_url_params(constants.PE_CONNECT_ENDPOINT_TOKEN, {"realm": "/individu"})
    response = httpx.post(url, data=data, timeout=30)

    if response.status_code not in [200, 201]:
        error_msg = "Impossible d'obtenir le jeton de PôleEmploiConnect."
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    token_data = response.json()

    if not token_data or "access_token" not in token_data:
        error_msg = "Aucun champ « access_token » dans la réponse PôleEmploiConnect, impossible de vous authentifier"
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    access_token = token_data["access_token"]

    # A token has been provided so it's time to fetch associated user infos
    # because the token is only valid for 5 seconds.
    url = constants.PE_CONNECT_ENDPOINT_USERINFO

    response = httpx.get(
        url,
        params={"schema": "openid"},
        headers={"Authorization": "Bearer " + access_token},
        timeout=60,
    )
    if response.status_code != 200:
        error_msg = "Impossible d'obtenir les informations utilisateur de PôleEmploiConnect."
        return _redirect_to_job_seeker_login_on_error(error_msg)

    try:
        user_data = json.loads(response.content.decode("utf-8"))
    except json.decoder.JSONDecodeError:
        error_msg = "Impossible de décoder les informations utilisateur."
        return _redirect_to_job_seeker_login_on_error(error_msg)

    if "sub" not in user_data:
        # 'sub' is the unique identifier from PôleEmploiConnect, we need that to match a user later on
        error_msg = "Le paramètre « sub » n'a pas été retourné par PôleEmploiConnect. Il est nécessaire pour identifier un utilisateur."  # noqa E501
        logger.error(error_msg)
        return _redirect_to_job_seeker_login_on_error(error_msg)

    try:
        pe_user_data = PoleEmploiConnectUserData.from_user_info(user_data)
    except KeyError as e:
        if "email" in e.args:
            return HttpResponseRedirect(reverse("pe_connect:no_email"))
        messages.error(request, "Une erreur technique est survenue, impossible de vous connecter avec Pôle Emploi.")
        return HttpResponseRedirect("search:siaes_home")

    try:
        # At this step, we can update the user's fields in DB and create a session if required
        user, _ = pe_user_data.create_or_update_user()
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

    # Fetch external data if never done
    latest_pe_data_import = user.externaldataimport_set.pe_sources().first()
    if latest_pe_data_import is None or latest_pe_data_import.status != ExternalDataImport.STATUS_OK:
        # No data for user or the import failed last time
        # Async via Huey
        huey_import_user_pe_data(user, access_token, latest_pe_data_import)

    # Because we have more than one Authentication backend in our settings, we need to specify
    # the one we want to use in login
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    # Keep token_data["id_token"] to logout from PEAMU
    request.session[constants.PE_CONNECT_SESSION_TOKEN] = token_data["id_token"]
    request.session[constants.PE_CONNECT_SESSION_STATE] = state
    request.session.modified = True

    next_url = reverse("dashboard:index")
    return HttpResponseRedirect(next_url)


def pe_connect_no_email(request, template_name="account/peamu_no_email.html"):
    return render(request, template_name)


def pe_connect_logout(request):
    id_token = request.GET.get("id_token")

    if not id_token:
        return JsonResponse({"message": "Le paramètre « id_token » est manquant."}, status=400)

    params = {
        "id_token_hint": id_token,
        "redirect_uri": get_absolute_url(reverse("search:siaes_home")),
    }
    url = constants.PE_CONNECT_ENDPOINT_LOGOUT
    complete_url = f"{url}?{urlencode(params)}"
    return HttpResponseRedirect(complete_url)
