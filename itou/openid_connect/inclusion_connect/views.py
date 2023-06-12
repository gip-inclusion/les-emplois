import dataclasses
import logging

import httpx
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
from itou.utils import constants as global_constants
from itou.utils.constants import ITOU_ASSISTANCE_URL
from itou.utils.urls import add_url_params, get_absolute_url

from ..models import InvalidKindException, MultipleUsersFoundException
from . import constants
from .enums import InclusionConnectChannel
from .models import InclusionConnectPrescriberData, InclusionConnectSiaeStaffData, InclusionConnectState


logger = logging.getLogger(__name__)


USER_DATA_CLASSES = {
    KIND_PRESCRIBER: InclusionConnectPrescriberData,
    KIND_SIAE_STAFF: InclusionConnectSiaeStaffData,
}


@dataclasses.dataclass
class InclusionConnectStateData:
    previous_url: str = None
    next_url: str = None
    user_email: str = None
    user_kind: str = None
    user_firstname: str = None
    user_lastname: str = None
    channel: str = None
    # Tells us where did the user came from so that we can adapt
    # error messages in the callback view.
    is_login: bool = False  # Used to skip kind check and allow login through the wrong user kind
    prescriber_session_data: dict = None

    def asdict(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class InclusionConnectSession:
    key: str = constants.INCLUSION_CONNECT_SESSION_KEY
    token: str = None
    state: str = None

    def asdict(self):
        return dataclasses.asdict(self)

    def bind_to_request(self, request):
        request.session[self.key] = dataclasses.asdict(self)


def _redirect_to_login_page_on_error(error_msg=None, request=None):
    if request:
        messages.error(request, "Une erreur technique est survenue. Merci de recommencer.")
    if error_msg:
        logger.error(error_msg, exc_info=True)
    return HttpResponseRedirect(reverse("home:hp"))


def _generate_inclusion_params_from_session(ic_data):
    redirect_uri = get_absolute_url(reverse("inclusion_connect:callback"))
    state = InclusionConnectState.save_state(data=ic_data)
    data = {
        "response_type": "code",
        "client_id": constants.INCLUSION_CONNECT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": constants.INCLUSION_CONNECT_SCOPES,
        "state": state,
        "nonce": crypto.get_random_string(length=12),
    }
    if (user_email := ic_data.get("user_email")) is not None:
        data["login_hint"] = user_email
    if (lastname := ic_data.get("user_lastname")) is not None:
        data["lastname"] = lastname
    if (firstname := ic_data.get("user_firstname")) is not None:
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
    register = request.GET.get("register")
    if not user_kind:
        return _redirect_to_login_page_on_error(error_msg="User kind missing.")

    ic_data = InclusionConnectStateData(
        user_kind=user_kind, previous_url=previous_url, next_url=next_url, is_login=not register
    )

    user_email = request.GET.get("user_email")
    channel = request.GET.get("channel")
    if user_email:
        ic_data.user_email = user_email
        ic_data.channel = channel
        ic_data.user_firstname = request.GET.get("user_firstname")
        ic_data.user_lastname = request.GET.get("user_lastname")

    if session_data := request.session.get(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY):
        ic_data.prescriber_session_data = {global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY: session_data}

    data = _generate_inclusion_params_from_session(ic_data.asdict())
    # Store the state in session to allow the user to use resume registration view
    ic_session = InclusionConnectSession(state=data["state"])
    ic_session.bind_to_request(request)

    if register:
        base_url = constants.INCLUSION_CONNECT_ENDPOINT_REGISTER
    else:
        base_url = constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE
    return HttpResponseRedirect(f"{base_url}?{urlencode(data)}")


# TODO(alaurent) Remove a few days after IC django is Live
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

    ic_state = InclusionConnectState.get_from_csrf(ic_session["state"])

    # TODO(alaurent) Remove after a few days (until all users asking for help could follow this link)
    # Backward compatibility:
    if ic_state is None or not ic_state.data:
        data = _generate_inclusion_params_from_session(ic_session)
        return HttpResponseRedirect(f"{constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE}?{urlencode(data)}")

    if ic_state is None:
        messages.error(request, "Impossible de reprendre la création de compte.")
        return HttpResponseRedirect(reverse("home:hp"))

    data = _generate_inclusion_params_from_session(ic_state.data)
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

    # Check if state is valid and session exists
    ic_state = InclusionConnectState.get_from_csrf(state)
    if ic_state is None or not ic_state.is_valid():
        return _redirect_to_login_page_on_error(request=request)
    ic_session = request.session.get(constants.INCLUSION_CONNECT_SESSION_KEY)
    if ic_session and not ic_state.data:
        # TODO(alaurent) Backward compatibility: Remove after a few days
        # Keep token_data["id_token"] to logout from IC.
        # At this step, we can update the user's fields in DB
        ic_session["token"] = token_data["id_token"]
        ic_session["state"] = state
        request.session.modified = True
        ic_state.data = ic_session
    else:
        ic_session = InclusionConnectSession(state=state, token=token_data["id_token"])
        ic_session.bind_to_request(request)

    # A token has been provided so it's time to fetch associated user infos
    # because the token is only valid for 5 seconds.
    # We don't really need to access user_info since all we need is already in the access_token.
    # Should we remove this ?
    user_data, error_rediction = _get_user_info(request, access_token)
    if error_rediction:
        return error_rediction

    if "sub" not in user_data:
        # 'sub' is the unique identifier from Inclusion Connect, we need that to match a user later on.
        return _redirect_to_login_page_on_error(error_msg="Sub parameter error.", request=request)

    user_kind = ic_state.data["user_kind"]
    is_successful = True
    ic_user_data = USER_DATA_CLASSES[user_kind].from_user_info(user_data)
    ic_session_email = ic_state.data.get("user_email")

    if ic_session_email and ic_session_email.lower() != ic_user_data.email.lower():
        if ic_state.data["channel"] == InclusionConnectChannel.INVITATION:
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
        user, _ = ic_user_data.create_or_update_user(is_login=ic_state.data.get("is_login"))
    except InvalidKindException:
        existing_user = User.objects.get(email=user_data["email"])
        _add_user_kind_error_message(request, existing_user, user_kind)
        is_successful = False
    except MultipleUsersFoundException as e:
        # Here we have a user trying to update his email, but with an already existing email
        # let him login, but display a message because we didn't update his email
        messages.error(
            request,
            mark_safe(
                "Vous avez modifié votre e-mail sur Inclusion Connect, mais celui-ci est déjà associé à un compte "
                f"sur la plateforme. Nous n'avons donc pas pu mettre à jour {e.users[0].email} en {e.users[1].email}. "
                "Veuillez vous rapprocher du support pour débloquer la situation en suivant "
                "<a href='https://communaute.inclusion.beta.gouv.fr/aide/emplois/#support'>ce lien</a>."
            ),
        )
        user = e.users[0]

    if not is_successful:
        logout_url_params = {
            "redirect_url": ic_state.data["previous_url"],
        }
        next_url = f"{reverse('inclusion_connect:logout')}?{urlencode(logout_url_params)}"
        return HttpResponseRedirect(next_url)

    # Because we have more than one Authentication backend in our settings, we need to specify
    # the one we want to use in login
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    # reattach prescriber session
    if prescriber_session_data := ic_state.data.get("prescriber_session_data"):
        request.session.update(prescriber_session_data)

    next_url = ic_state.data["next_url"] or get_adapter(request).get_login_redirect_url(request)
    return HttpResponseRedirect(next_url)


def inclusion_connect_logout(request):
    token = request.GET.get("token")
    post_logout_redirect_url = request.GET.get("redirect_url", reverse("home:hp"))

    # Fallback on session data.
    if not token:
        ic_session = request.session.get(constants.INCLUSION_CONNECT_SESSION_KEY)
        if not ic_session:
            raise KeyError("Missing session key.")
        token = ic_session["token"]

    params = {
        "id_token_hint": token,
        "post_logout_redirect_uri": get_absolute_url(post_logout_redirect_url),
    }
    complete_url = add_url_params(constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT, params)
    return HttpResponseRedirect(complete_url)
