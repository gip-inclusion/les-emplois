import dataclasses
import logging

import httpx
import jwt
from allauth.account.adapter import get_adapter
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import crypto
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme, urlencode

from itou.openid_connect.errors import redirect_with_error_sso_email_conflict_on_registration
from itou.openid_connect.models import EmailInUseException, InvalidKindException, MultipleUsersFoundException
from itou.openid_connect.pro_connect import constants
from itou.openid_connect.pro_connect.enums import ProConnectChannel
from itou.openid_connect.pro_connect.models import ProConnectEmployerData, ProConnectPrescriberData, ProConnectState
from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import KIND_EMPLOYER, KIND_PRESCRIBER, IdentityProvider, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.constants import ITOU_HELP_CENTER_URL
from itou.utils.urls import add_url_params, get_absolute_url, get_safe_url
from itou.www.invitations_views.helpers import accept_all_pending_invitations


logger = logging.getLogger(__name__)

USER_DATA_CLASSES = {
    KIND_PRESCRIBER: ProConnectPrescriberData,
    KIND_EMPLOYER: ProConnectEmployerData,
}


@dataclasses.dataclass
class ProConnectStateData:
    previous_url: str = None
    next_url: str = None
    user_email: str = None
    user_kind: str = None
    channel: str = None
    # Tells us where did the user came from so that we can adapt
    # error messages in the callback view.
    is_login: bool = False  # Used to skip kind check and allow login through the wrong user kind
    prescriber_session_data: dict = None


@dataclasses.dataclass
class ProConnectSession:
    key: str = constants.PRO_CONNECT_SESSION_KEY
    token: str = None
    state: str = None

    def bind_to_request(self, request):
        request.session[self.key] = dataclasses.asdict(self)


def _redirect_to_login_page_on_error(error_msg=None, request=None):
    if request:
        messages.error(request, "Une erreur technique est survenue. Merci de recommencer.")
    if error_msg:
        logger.error(error_msg, exc_info=True)
    return HttpResponseRedirect(reverse("search:employers_home"))


def _generate_pro_params_from_session(pc_data):
    redirect_uri = get_absolute_url(reverse("pro_connect:callback"))
    state = ProConnectState.save_state(data=pc_data)
    data = {
        "response_type": "code",
        "client_id": constants.PRO_CONNECT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "acr_values": "eidas1",
        "scope": constants.PRO_CONNECT_SCOPES,
        "state": state,
        "nonce": crypto.get_random_string(length=12),
    }
    if pc_data.get("channel") == ProConnectChannel.MAP_CONSEILLER:
        data["idp_hint"] = constants.PRO_CONNECT_FT_IDP_HINT
    if user_email := pc_data.get("user_email"):
        data["login_hint"] = user_email
    return data


def _add_user_kind_error_message(request, existing_user, new_user_kind):
    messages.error(
        request,
        format_html(
            "Un compte {} existe déjà avec cette adresse e-mail. "
            "Vous devez créer un compte ProConnect avec une autre adresse e-mail pour "
            "devenir {} sur la plateforme. Besoin d'aide ? "
            "<a href='{}/requests/new' target='_blank'>Contactez-nous</a>.",
            existing_user.get_kind_display(),
            UserKind(new_user_kind).label,
            ITOU_HELP_CENTER_URL,
        ),
    )


@login_not_required
def pro_connect_authorize(request):
    # Start a new session.
    user_kind = request.GET.get("user_kind")
    previous_url = get_safe_url(request, "previous_url", fallback_url=reverse("search:employers_home"))
    next_url = request.GET.get("next_url")
    if next_url and not url_has_allowed_host_and_scheme(next_url, settings.ALLOWED_HOSTS, request.is_secure()):
        return _redirect_to_login_page_on_error(error_msg="Forbidden external url")
    register = request.GET.get("register")
    if not user_kind:
        return _redirect_to_login_page_on_error(error_msg="User kind missing.")
    if user_kind not in USER_DATA_CLASSES:
        return _redirect_to_login_page_on_error(error_msg="Wrong user kind.")

    pc_data = ProConnectStateData(
        user_kind=user_kind, previous_url=previous_url, next_url=next_url, is_login=not register
    )

    if channel := request.GET.get("channel"):
        pc_data.channel = channel

    if user_email := request.GET.get("user_email"):
        pc_data.user_email = user_email

    if session_data := request.session.get(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY):
        pc_data.prescriber_session_data = {global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY: session_data}

    data = _generate_pro_params_from_session(dataclasses.asdict(pc_data))
    # Store the state in session to allow the user to use resume registration view
    pc_session = ProConnectSession(state=data["state"])
    pc_session.bind_to_request(request)

    base_url = constants.PRO_CONNECT_ENDPOINT_AUTHORIZE
    return HttpResponseRedirect(f"{base_url}?{urlencode(data)}")


def _get_token(request, code):
    # Retrieve token from ProConnect
    token_redirect_uri = get_absolute_url(reverse("pro_connect:callback"))
    data = {
        "client_id": constants.PRO_CONNECT_CLIENT_ID,
        "client_secret": constants.PRO_CONNECT_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": token_redirect_uri,
    }
    response = httpx.post(
        constants.PRO_CONNECT_ENDPOINT_TOKEN,
        data=data,
        timeout=constants.PRO_CONNECT_TIMEOUT,
    )
    # Contains access_token, token_type, expires_in, id_token
    if response.status_code != 200:
        return None, _redirect_to_login_page_on_error(error_msg="Impossible to get token.", request=request)
    return response.json(), None


def _get_user_info(request, access_token):
    response = httpx.get(
        constants.PRO_CONNECT_ENDPOINT_USERINFO,
        params={"schema": "openid"},
        headers={"Authorization": "Bearer " + access_token},
        timeout=constants.PRO_CONNECT_TIMEOUT,
    )
    if response.status_code != 200:
        return None, _redirect_to_login_page_on_error(error_msg="Impossible to get user infos.", request=request)
    decoded_id_token = jwt.decode(
        response.content,
        key=constants.PRO_CONNECT_CLIENT_SECRET,
        algorithms=["HS256"],
        audience=constants.PRO_CONNECT_CLIENT_ID,
        # TODO: Remove once https://github.com/jpadilla/pyjwt/issues/939 is fixed
        options={"verify_iat": False},
    )
    return decoded_id_token, None


@login_not_required
def pro_connect_callback(request):
    code = request.GET.get("code")
    state = request.GET.get("state")
    if code is None or state is None:
        return _redirect_to_login_page_on_error(error_msg="Missing code or state.", request=request)

    # Get access token now to have more data in sentry
    token_data, error_redirection = _get_token(request, code)
    if error_redirection:
        return error_redirection
    access_token = token_data.get("access_token")
    if not access_token:
        return _redirect_to_login_page_on_error(error_msg="Access token field missing.", request=request)

    # Check if state is valid and session exists
    pro_connect_state = ProConnectState.get_from_state(state)
    if pro_connect_state is None or not pro_connect_state.is_valid():
        return _redirect_to_login_page_on_error(request=request)
    pc_session = ProConnectSession(state=state, token=token_data["id_token"])
    pc_session.bind_to_request(request)

    # A token has been provided so it's time to fetch associated user infos
    # because the token is only valid for 5 seconds.
    # We don't really need to access user_info since all we need is already in the access_token.
    # Should we remove this ?
    user_data, error_redirection = _get_user_info(request, access_token)
    if error_redirection:
        return error_redirection

    if "sub" not in user_data:
        # 'sub' is the unique identifier from ProConnect, we need that to match a user later on.
        return _redirect_to_login_page_on_error(error_msg="Sub parameter error.", request=request)

    user_kind = pro_connect_state.data["user_kind"]
    is_successful = True
    pc_user_data = USER_DATA_CLASSES[user_kind].from_user_info(user_data)
    pc_session_email = pro_connect_state.data.get("user_email")

    if pc_session_email and pc_session_email.lower() != pc_user_data.email.lower():
        if pro_connect_state.data["channel"] == ProConnectChannel.INVITATION:
            error = (
                "L’adresse e-mail que vous avez utilisée pour vous connecter avec ProConnect "
                f"({pc_user_data.email}) "
                f"ne correspond pas à l’adresse e-mail de l’invitation ({pc_session_email})."
            )
        else:
            error = (
                "L’adresse e-mail que vous avez utilisée pour vous connecter avec ProConnect "
                f"({pc_user_data.email}) "
                f"est différente de celle que vous avez indiquée précédemment ({pc_session_email})."
            )
        messages.error(request, error)
        is_successful = False

    try:
        user, _ = pc_user_data.create_or_update_user(is_login=pro_connect_state.data.get("is_login"))
    except InvalidKindException:
        existing_user = User.objects.get(email=user_data["email"])
        _add_user_kind_error_message(request, existing_user, user_kind)
        is_successful = False
    except EmailInUseException as e:
        return redirect_with_error_sso_email_conflict_on_registration(
            request, e.user, IdentityProvider.PRO_CONNECT.label
        )
    except MultipleUsersFoundException as e:
        # Here we have a user trying to update his email, but with an already existing email
        # let him login, but display a message because we didn't update his email
        messages.error(
            request,
            format_html(
                "L'adresse e-mail que nous a transmis ProConnect est différente de celle qui est enregistrée "
                "sur la plateforme des emplois, et est déjà associé à un autre compte. "
                "Nous n'avons donc pas pu mettre à jour {} en {}. "
                "Veuillez vous rapprocher du support pour débloquer la situation en suivant "
                "<a href='{}'>ce lien</a>.",
                e.users[0].email,
                e.users[1].email,
                global_constants.ITOU_HELP_CENTER_URL,
            ),
        )
        user = e.users[0]

    code_safir_pole_emploi = user_data.get("custom", {}).get("structureTravail")
    # Only handle user creation for the moment, not updates.
    if is_successful and user.is_prescriber and code_safir_pole_emploi:
        try:
            pc_user_data.join_org(user=user, safir=code_safir_pole_emploi)
        except PrescriberOrganization.DoesNotExist:
            messages.warning(
                request,
                format_html(
                    "L'agence indiquée par NEPTUNE (code SAFIR {}) n'est pas référencée dans notre service. "
                    "Cela arrive quand vous appartenez à un Point Relais mais que vous êtes rattaché à une agence "
                    "mère sur la plateforme des emplois. "
                    "Si vous pensez qu'il y a une erreur, vérifiez que le code SAFIR est le bon "
                    "puis <a href='{}'>contactez le support</a> en indiquant le code SAFIR.",
                    code_safir_pole_emploi,
                    global_constants.ITOU_HELP_CENTER_URL,
                ),
            )

    if not is_successful:
        logout_url_params = {
            "redirect_url": pro_connect_state.data["previous_url"],
        }
        next_url = f"{reverse('pro_connect:logout')}?{urlencode(logout_url_params)}"
        return HttpResponseRedirect(next_url)

    # Because we have more than one Authentication backend in our settings, we need to specify
    # the one we want to use in login
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    # reattach prescriber session
    if prescriber_session_data := pro_connect_state.data.get("prescriber_session_data"):
        request.session.update(prescriber_session_data)

    accept_all_pending_invitations(request)

    next_url = pro_connect_state.data["next_url"] or get_adapter(request).get_login_redirect_url(request)
    return HttpResponseRedirect(next_url)


@login_not_required
def pro_connect_logout(request):
    token = request.GET.get("token")
    post_logout_redirect_url = reverse("pro_connect:logout_callback")
    redirect_url = get_safe_url(request, "redirect_url", fallback_url=reverse("search:employers_home"))

    # Fallback on session data.
    if not token:
        pc_session = request.session.get(constants.PRO_CONNECT_SESSION_KEY)
        if not pc_session:
            raise KeyError("Missing session key.")
        token = pc_session["token"]

    logout_state = ProConnectState.save_state(data={"redirect_url": redirect_url})

    params = {
        "id_token_hint": token,
        "state": logout_state,
        "post_logout_redirect_uri": get_absolute_url(post_logout_redirect_url),
    }
    complete_url = add_url_params(constants.PRO_CONNECT_ENDPOINT_LOGOUT, params)
    return HttpResponseRedirect(complete_url)


@login_not_required
def pro_connect_logout_callback(request):
    state = request.GET.get("state")
    if state is None:
        return _redirect_to_login_page_on_error(error_msg="Missing state.", request=request)

    # Check if state is valid and session exists
    pro_connect_state = ProConnectState.get_from_state(state)
    if pro_connect_state is None or not pro_connect_state.is_valid():
        return _redirect_to_login_page_on_error(request=request)

    return HttpResponseRedirect(pro_connect_state.data["redirect_url"])
