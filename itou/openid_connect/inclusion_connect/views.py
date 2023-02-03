import dataclasses
import logging
from urllib.error import HTTPError

import httpx
import jwt
from allauth.account.adapter import get_adapter
from django.contrib import messages
from django.contrib.auth import login
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import crypto
from django.utils.http import urlencode
from django.utils.safestring import mark_safe

from itou.users.enums import KIND_PRESCRIBER, KIND_SIAE_STAFF, IdentityProvider, UserKind
from itou.users.models import User
from itou.utils.constants import ITOU_ASSISTANCE_URL
from itou.utils.urls import get_absolute_url

from ..models import InvalidKindException
from . import constants
from .enums import InclusionConnectChannel
from .models import InclusionConnectPrescriberData, InclusionConnectSiaeStaffData, InclusionConnectState


logger = logging.getLogger(__name__)


USER_DATA_CLASSES = {
    KIND_PRESCRIBER: InclusionConnectPrescriberData,
    KIND_SIAE_STAFF: InclusionConnectSiaeStaffData,
}


@dataclasses.dataclass
class InclusionConnectSession:
    token: str = None
    state: str = None
    previous_url: str = None
    next_url: str = None
    user_email: str = None
    user_kind: str = None
    user_firstname: str = None
    user_lastname: str = None
    request: str = None
    key: str = constants.INCLUSION_CONNECT_SESSION_KEY
    channel: str = None
    # Tells us where did the user came from so that we can adapt
    # error messages in the callback view.

    def asdict(self):
        return dataclasses.asdict(self)

    def bind_to_request(self, request):
        request.session[self.key] = dataclasses.asdict(self)
        request.session.has_changed = True
        return request


def _redirect_to_login_page_on_error(error_msg, request=None):
    if request:
        messages.error(request, "Une erreur technique est survenue. Merci de recommencer.")
    logger.error(error_msg, exc_info=True)
    return HttpResponseRedirect(reverse("home:hp"))


def _generate_inclusion_params_from_session(ic_session):
    redirect_uri = get_absolute_url(reverse("inclusion_connect:callback"))
    signed_csrf = InclusionConnectState.create_signed_csrf_token()
    data = {
        "response_type": "code",
        "client_id": constants.INCLUSION_CONNECT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": constants.INCLUSION_CONNECT_SCOPES,
        "state": signed_csrf,
        "nonce": crypto.get_random_string(length=12),
    }
    if (user_email := ic_session.get("user_email")) is not None:
        data["login_hint"] = user_email
    if (lastname := ic_session.get("user_lastname")) is not None:
        data["lastname"] = lastname
    if (firstname := ic_session.get("user_firstname")) is not None:
        data["firstname"] = firstname
    return data


def _add_user_kind_error_message(request, existing_user, new_user_kind):
    error = (
        f"Un compte {existing_user.get_kind_display()} existe déjà avec cette adresse e-mail. "
        "Vous devez créer un compte Inclusion Connect avec une autre adresse e-mail pour "
        f"devenir {UserKind(new_user_kind).label} sur la plateforme. Besoin d'aide ? "
        f"<a href='{ITOU_ASSISTANCE_URL}/#support' target='_blank'>Contactez-nous</a>."
    )
    messages.error(request, mark_safe(error))


def inclusion_connect_authorize(request):
    # Start a new session.
    user_kind = request.GET.get("user_kind")
    previous_url = request.GET.get("previous_url", reverse("home:hp"))
    next_url = request.GET.get("next_url")
    if not user_kind:
        return _redirect_to_login_page_on_error(error_msg="User kind missing.")

    ic_session = InclusionConnectSession(user_kind=user_kind, previous_url=previous_url, next_url=next_url)
    request = ic_session.bind_to_request(request)
    ic_session = request.session[constants.INCLUSION_CONNECT_SESSION_KEY]

    user_email = request.GET.get("user_email")
    channel = request.GET.get("channel")
    if user_email:
        ic_session["user_email"] = user_email
        ic_session["channel"] = channel
        ic_session["user_firstname"] = request.GET.get("user_firstname")
        ic_session["user_lastname"] = request.GET.get("user_lastname")
        request.session.modified = True

    data = _generate_inclusion_params_from_session(ic_session)

    if request.GET.get("register"):
        base_url = constants.INCLUSION_CONNECT_ENDPOINT_REGISTER
    else:
        base_url = constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE
    return HttpResponseRedirect(f"{base_url}?{urlencode(data)}")


def inclusion_connect_resume_registration(request):
    """
    Used for users that didn't received the validation e-mail from Inclusion Connect.
    This view will allow them to resume the account creation flow.
    The only way to get the URL is to get it from the support team.
    """
    ic_session = request.session.get(constants.INCLUSION_CONNECT_SESSION_KEY)
    # If there's a token in the session then the user already came back to the callback view : nothing to resume.
    # If there's no session then the user never started a registration on this device : nothing to resume either.
    if not ic_session or ic_session["token"]:
        messages.error(request, "Impossible de reprendre la création de compte.")
        return HttpResponseRedirect(reverse("home:hp"))
    data = _generate_inclusion_params_from_session(ic_session)
    return HttpResponseRedirect(f"{constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE}?{urlencode(data)}")


def inclusion_connect_activate_account(request):
    params = request.GET.copy()
    email = params.get("user_email")
    if not email:
        return HttpResponseRedirect(params.get("previous_url", reverse("home:hp")))

    user_kind = params.get("user_kind")
    user = User.objects.filter(email=email).first()

    if not user:
        params["register"] = True
        request.GET = params
        return inclusion_connect_authorize(request)

    if user.kind != user_kind:
        _add_user_kind_error_message(request, user, request.GET.get("user_kind"))
        return HttpResponseRedirect(params.get("previous_url", reverse("home:hp")))

    if user.identity_provider == IdentityProvider.INCLUSION_CONNECT:
        params["channel"] = InclusionConnectChannel.ACTIVATION
        request.GET = params
        return inclusion_connect_authorize(request)

    params["channel"] = InclusionConnectChannel.ACTIVATION
    params["user_firstname"] = user.first_name
    params["user_lastname"] = user.last_name
    params["register"] = True
    request.GET = params
    return inclusion_connect_authorize(request)


def _get_token(request, code):
    # Retrieve token from Inclusion Connect
    token_redirect_uri = get_absolute_url(reverse("inclusion_connect:callback"))
    data = {
        "client_id": constants.INCLUSION_CONNECT_CLIENT_ID,
        "client_secret": constants.INCLUSION_CONNECT_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": token_redirect_uri,
    }
    response = httpx.post(
        constants.INCLUSION_CONNECT_ENDPOINT_TOKEN,
        data=data,
        timeout=constants.INCLUSION_CONNECT_TIMEOUT,
    )
    # Contains access_token, token_type, expires_in, id_token
    if response.status_code != 200:
        return None, _redirect_to_login_page_on_error(error_msg="Impossible to get IC token.", request=request)
    return response.json(), None


def _get_user_info(request, access_token):
    response = httpx.get(
        constants.INCLUSION_CONNECT_ENDPOINT_USERINFO,
        params={"schema": "openid"},
        headers={"Authorization": "Bearer " + access_token},
        timeout=constants.INCLUSION_CONNECT_TIMEOUT,
    )
    if response.status_code != 200:
        return None, _redirect_to_login_page_on_error(error_msg="Impossible to get user infos.", request=request)
    return response.json(), None


def inclusion_connect_callback(request):  # pylint: disable=too-many-return-statements
    code = request.GET.get("code")
    state = request.GET.get("state")
    if code is None or state is None:
        return _redirect_to_login_page_on_error(error_msg="Missing code or state.", request=request)

    # Get access token now to have more data in sentry
    token_data, error_rediction = _get_token(request, code)
    if error_rediction:
        return error_rediction
    access_token = token_data.get("access_token")
    if not access_token:
        return _redirect_to_login_page_on_error(error_msg="Access token field missing.", request=request)
    decode_access_token = jwt.decode(access_token, algorithms=["RS256"], options={"verify_signature": False})

    # Check if state is valid and session exists
    ic_state = InclusionConnectState.get_from_csrf(state)
    if ic_state is None or not ic_state.is_valid():
        return _redirect_to_login_page_on_error(error_msg="Invalid state.", request=request)
    ic_session = request.session.get(constants.INCLUSION_CONNECT_SESSION_KEY)
    if ic_session is None:
        return _redirect_to_login_page_on_error(error_msg="Missing session.", request=request)

    # Keep token_data["id_token"] to logout from IC.
    # At this step, we can update the user's fields in DB
    ic_session["token"] = token_data["id_token"]
    ic_session["state"] = state
    request.session.modified = True

    # A token has been provided so it's time to fetch associated user infos
    # because the token is only valid for 5 seconds.
    # We don't really need to access user_info since all we need is already in the access_token.
    # Should we remove this ?
    user_data, error_rediction = _get_user_info(request, access_token)
    if error_rediction:
        return error_rediction

    if "sub" not in user_data or user_data["sub"] != decode_access_token["sub"]:
        # 'sub' is the unique identifier from Inclusion Connect, we need that to match a user later on.
        return _redirect_to_login_page_on_error(error_msg="Sub parameter error.", request=request)

    user_kind = ic_session["user_kind"]
    is_successful = True
    ic_user_data = USER_DATA_CLASSES[user_kind].from_user_info(user_data)
    ic_session_email = ic_session.get("user_email")

    if ic_session_email and ic_session_email != ic_user_data.email:
        if ic_session["channel"] == InclusionConnectChannel.INVITATION:
            error = (
                "L’adresse e-mail que vous avez utilisée pour vous connecter avec Inclusion Connect "
                f"({ic_user_data.email}) "
                f"ne correspond pas à l’adresse e-mail de l’invitation ({ic_session_email})."
            )
        else:
            error = (
                "L’adresse e-mail que vous avez utilisée pour vous connecter avec Inclusion Connect "
                f"({ic_user_data.email}) "
                f"est différente de celle que vous avez indiquée précédemment ({ic_session_email})."
            )
        messages.error(request, error)
        is_successful = False

    try:
        user, _ = ic_user_data.create_or_update_user()
    except InvalidKindException:
        existing_user = User.objects.get(email=user_data["email"])
        _add_user_kind_error_message(request, existing_user, user_kind)
        is_successful = False

    if not is_successful:
        logout_url_params = {
            "redirect_url": ic_session["previous_url"],
        }
        next_url = f"{reverse('inclusion_connect:logout')}?{urlencode(logout_url_params)}"
        return HttpResponseRedirect(next_url)

    # Because we have more than one Authentication backend in our settings, we need to specify
    # the one we want to use in login
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    next_url = ic_session["next_url"] or get_adapter(request).get_login_redirect_url(request)
    return HttpResponseRedirect(next_url)


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
    }
    complete_url = f"{constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT}?{urlencode(params)}"
    # Logout user from IC with HTTPX to benefit from respx in tests
    # and to handle post logout redirection more easily.
    # It's okay if there's an error on Inclusion Connect : we don't want to crash on our side.
    try:
        response = httpx.get(complete_url)
    except HTTPError as e:
        logger.exception("Error during IC logout : '%s'", e)
    else:
        if response.status_code != 200:
            logger.error("Error during IC logout. Status code: %s", response.status_code)
    return HttpResponseRedirect(post_logout_redirect_url)
