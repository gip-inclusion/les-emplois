import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import crypto
from django.utils.html import format_html
from django.utils.http import urlencode
from py_identity_model import (
    AuthorizationCodeTokenRequest,
    DiscoveryDocumentRequest,
    PyIdentityModelException,
    TokenValidationConfig,
    UserInfoRequest,
    build_authorization_url,
    get_discovery_document,
    get_userinfo,
    request_authorization_code_token,
    validate_id_token,
)

from itou.external_data.tasks import huey_import_user_ft_data
from itou.openid_connect.errors import redirect_with_error_sso_email_conflict_on_registration
from itou.openid_connect.ft_connect import constants
from itou.openid_connect.ft_connect.models import FranceTravailConnectState, FranceTravailConnectUserData
from itou.openid_connect.models import (
    EmailInUseException,
    InactiveUserException,
    InvalidKindException,
    MultipleSubSameEmailException,
    MultipleUsersFoundException,
)
from itou.openid_connect.utils import init_user_nir_from_session
from itou.users.enums import IdentityProvider
from itou.utils import constants as global_constants, triggers
from itou.utils.readonly import http_methods
from itou.utils.urls import get_absolute_url
from itou.utils.views import with_triggers_context


logger = logging.getLogger(__name__)


def _redirect_to_job_seeker_login_on_error(error_msg, request, extra_tags=""):
    messages.error(request, error_msg, extra_tags)
    return HttpResponseRedirect(reverse("account_login"))


@login_not_required
def ft_connect_authorize(request):
    disco_doc = get_discovery_document(DiscoveryDocumentRequest(address=constants.FRANCETRAVAIL_CONNECT_DISCOVERY))
    # The redirect_uri should be defined in the France Travail Connect settings to be allowed
    # NB: the integration platform allows "http://127.0.0.1:8000/ft_connect/callback"
    redirect_uri = get_absolute_url(reverse("ft_connect:callback"), host=request.get_host())
    nonce = crypto.get_random_string(12)
    state = FranceTravailConnectState.save_state(nonce=nonce)
    print(constants.FRANCETRAVAIL_CONNECT_DISCOVERY)

    auth_url = build_authorization_url(
        authorization_endpoint=disco_doc.authorization_endpoint,
        client_id=settings.API_ESD["KEY"],
        redirect_uri=redirect_uri,
        scope=constants.FRANCETRAVAIL_CONNECT_SCOPES,
        state=state,
        nonce="nonce",
        realm="/individu",  # France Travail Connect specificity
    )
    return HttpResponseRedirect(auth_url)


# This view expects a GET but is not readonly (it is likely to create/update an user):
# we need a transaction and a postgres context for our triggers
@login_not_required
@http_methods(db_write=["GET"])
@with_triggers_context(methods=["GET"])
def ft_connect_callback(request):
    code = request.GET.get("code")
    if code is None:
        error_msg = (
            f"{IdentityProvider.FT_CONNECT.label} n’a pas transmis le paramètre « code » "
            "nécessaire à votre authentification."
        )
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    state = request.GET.get("state")
    ft_state = FranceTravailConnectState.get_from_state(state)
    if not ft_state or not ft_state.is_valid():
        error_msg = (
            f"Le paramètre « state » fourni par {IdentityProvider.FT_CONNECT.label} et nécessaire à votre "
            "authentification n’est pas valide."
        )
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    redirect_uri = get_absolute_url(reverse("ft_connect:callback"), host=request.get_host())

    disco_doc = get_discovery_document(DiscoveryDocumentRequest(address=constants.FRANCETRAVAIL_CONNECT_DISCOVERY))
    token_request = AuthorizationCodeTokenRequest(
        address=disco_doc.token_endpoint,
        client_id=settings.API_ESD["KEY"],
        client_secret=settings.API_ESD["SECRET"],
        code=code,
        redirect_uri=redirect_uri,
    )
    token_response = request_authorization_code_token(token_request)

    if not token_response.is_successful:
        print(token_response.error)
        logger.error("FT Connect token request failed", exc_info=True)
        error_msg = (
            f"Impossible d'obtenir le jeton de {IdentityProvider.FT_CONNECT.label}. Réessayez dans quelques minutes."
        )
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    # id_token reçu dans token_response.token["id_token"] (étape précédente)
    id_token = token_response.token["id_token"]
    access_token = token_response.token.get("access_token")

    if not access_token:
        error_msg = (
            f"Aucun champ « access_token » dans la réponse {IdentityProvider.FT_CONNECT.label}, "
            "impossible de vous authentifier"
        )
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    config = TokenValidationConfig(
        perform_disco=True,
        audience=settings.API_ESD["KEY"],
    )

    try:
        claims = validate_id_token(
            id_token=id_token,
            token_validation_config=config,
            disco_doc_address=constants.FRANCETRAVAIL_CONNECT_DISCOVERY,
            nonce=ft_state.nonce,
            access_token=access_token,  # Verify at_hash if present
        )
    except PyIdentityModelException as e:
        error_msg = f"Le jeton d’authentification de {IdentityProvider.FT_CONNECT.label} est invalide."
        logger.error("FT Connect id_token decode error: %s", e)
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    # A token has been provided so it's time to fetch associated user infos
    # because the token is only valid for 5 seconds.
    userinfo_request = UserInfoRequest(
        address=disco_doc.userinfo_endpoint,
        token=access_token,
        expected_sub=claims["sub"],  # optional : check the sub is the same as in the id_token
    )
    userinfo_response = get_userinfo(userinfo_request)

    if not userinfo_response.is_successful:
        print(userinfo_response.error)
        logger.error("FT Connect user info request failed", exc_info=True)
        error_msg = (
            f"Impossible d'obtenir les informations utilisateur de {IdentityProvider.FT_CONNECT.label}. "
            "Réessayez dans quelques minutes."
        )
        return _redirect_to_job_seeker_login_on_error(error_msg, request)

    try:
        ft_user_data = FranceTravailConnectUserData.from_user_info(userinfo_response.claims)
    except KeyError as e:
        if "email" in e.args:
            return HttpResponseRedirect(reverse("ft_connect:no_email"))
        messages.error(request, "Une erreur technique est survenue, impossible de vous connecter avec France Travail.")
        return HttpResponseRedirect(reverse("search:employers_home"))

    try:
        # At this step, we can update the user's fields in DB and create a session if required
        user, _ = ft_user_data.create_or_update_user()
    except InactiveUserException as e:
        logger.info("FT Connect login attempt with inactive user: %s", e.user)
        return _redirect_to_job_seeker_login_on_error(
            e.format_message_html(IdentityProvider.FT_CONNECT), request=request
        )
    except InvalidKindException:
        messages.info(request, "Ce compte existe déjà, veuillez vous connecter.")
        return HttpResponseRedirect(reverse("account_login"))
    except MultipleSubSameEmailException as e:
        return _redirect_to_job_seeker_login_on_error(
            e.format_message_html(IdentityProvider.FT_CONNECT), request=request
        )
    except MultipleUsersFoundException as e:
        return _redirect_to_job_seeker_login_on_error(
            format_html(
                "Vous avez deux comptes sur la plateforme et nous détectons un conflit d'email : "
                "{} et {}. "
                "Veuillez vous rapprocher du support pour débloquer la situation en suivant "
                "<a href='{}'>ce lien</a>.",
                e.users[0].email,
                e.users[1].email,
                global_constants.ITOU_HELP_CENTER_URL,
            ),
            request=request,
        )
    except EmailInUseException as e:
        return redirect_with_error_sso_email_conflict_on_registration(
            request, e.user, IdentityProvider.FT_CONNECT.label
        )

    init_user_nir_from_session(request, user)

    # Fetch external data if birthdate or address is missing
    if not user.jobseeker_profile.birthdate or not user.address_on_one_line:
        triggers_context = triggers.get_current_context() or {}
        huey_import_user_ft_data(user, access_token, triggers_context=triggers_context)

    # Keep token_data["id_token"] to logout from France Travail Connect
    request.session[constants.FRANCETRAVAIL_CONNECT_SESSION_TOKEN] = id_token
    request.session.modified = True

    login(request, user)

    next_url = reverse("dashboard:index")
    return HttpResponseRedirect(next_url)


@login_not_required
def ft_connect_no_email(request, template_name="account/ft_connect_no_email.html"):
    return render(request, template_name)


@login_not_required
def ft_connect_logout(request):
    id_token = request.GET.get("id_token")

    if not id_token:
        return JsonResponse({"message": "Le paramètre « id_token » est manquant."}, status=400)

    params = {
        "id_token_hint": id_token,
        "redirect_uri": get_absolute_url(reverse("search:employers_home"), host=request.get_host()),
    }
    url = constants.FRANCETRAVAIL_CONNECT_ENDPOINT_LOGOUT
    complete_url = f"{url}?{urlencode(params)}"
    return HttpResponseRedirect(complete_url)
