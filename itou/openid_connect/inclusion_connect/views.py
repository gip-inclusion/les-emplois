import dataclasses
import json
import logging

import httpx
from allauth.account.adapter import get_adapter
from django.conf import settings  # TODO: move to itou.prescribers.constants
from django.contrib import messages
from django.contrib.auth import login
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import crypto
from django.utils.http import urlencode
from django.utils.safestring import mark_safe

from itou.users.enums import KIND_PRESCRIBER
from itou.users.models import User
from itou.utils.urls import get_absolute_url

from ..models import TooManyKindsException
from . import constants
from .models import InclusionConnectState, InclusionConnectUserData


logger = logging.getLogger(__name__)


@dataclasses.dataclass
class InclusionConnectSession:
    token: str = None
    state: str = None
    previous_url: str = None
    next_url: str = None
    user_email: str = None
    user_kind: str = None
    request: str = None
    key: str = constants.INCLUSION_CONNECT_SESSION_KEY

    def asdict(self):
        return dataclasses.asdict(self)

    def bind_to_request(self, request):
        request.session[self.key] = dataclasses.asdict(self)
        request.session.has_changed = True
        return request


def _redirect_to_login_page_on_error(error_msg, request=None):
    if request:
        messages.error(request, "Une erreur technique est survenue. Merci de recommencer.")
    logger.error(error_msg)
    return HttpResponseRedirect(reverse("login:job_seeker"))


def inclusion_connect_authorize(request):
    # Start a new session.
    user_kind = request.GET.get("user_kind")
    previous_url = request.GET.get("previous_url", reverse("home:hp"))
    next_url = request.GET.get("next_url")
    if not user_kind:
        raise KeyError("User kind missing.")

    ic_session = InclusionConnectSession(user_kind=user_kind, previous_url=previous_url, next_url=next_url)
    request = ic_session.bind_to_request(request)
    ic_session = request.session[constants.INCLUSION_CONNECT_SESSION_KEY]

    redirect_uri = get_absolute_url(reverse("inclusion_connect:callback"))
    signed_csrf = InclusionConnectState.create_signed_csrf_token()
    data = {
        "response_type": "code",
        "client_id": constants.INCLUSION_CONNECT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": constants.INCLUSION_CONNECT_SCOPES,
        "state": signed_csrf,
        "nonce": crypto.get_random_string(length=12),
        "from": "emplois",  # Display a "Les emplois" logo on the connection page.
    }
    login_hint = request.GET.get("login_hint")
    if login_hint:
        data["login_hint"] = login_hint
        ic_session["user_email"] = login_hint
        request.session.modified = True

    return HttpResponseRedirect(f"{constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE}?{urlencode(data)}")


def inclusion_connect_callback(request):  # pylint: disable=too-many-return-statements
    code = request.GET.get("code")
    state = request.GET.get("state")
    if code is None or not InclusionConnectState.is_valid(state):
        return _redirect_to_login_page_on_error(error_msg="Missing code or invalid state.", request=request)

    ic_session = request.session[constants.INCLUSION_CONNECT_SESSION_KEY]
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

    if response.status_code != 200:
        return _redirect_to_login_page_on_error(error_msg="Impossible to get IC token.", request=request)

    # Contains access_token, token_type, expires_in, id_token
    token_data = response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return _redirect_to_login_page_on_error(error_msg="Access token field missing.", request=request)

    # Keep token_data["id_token"] to logout from IC.
    # At this step, we can update the user's fields in DB and create a session if required.
    ic_session["token"] = token_data["id_token"]
    ic_session["state"] = state
    request.session.modified = True

    # A token has been provided so it's time to fetch associated user infos
    # because the token is only valid for 5 seconds.
    response = httpx.get(
        constants.INCLUSION_CONNECT_ENDPOINT_USERINFO,
        params={"schema": "openid"},
        headers={"Authorization": "Bearer " + access_token},
        timeout=constants.INCLUSION_CONNECT_TIMEOUT,
    )
    if response.status_code != 200:
        return _redirect_to_login_page_on_error(error_msg="Impossible to get user infos.", request=request)

    try:
        user_data = json.loads(response.content.decode("utf-8"))
    except json.decoder.JSONDecodeError:
        return _redirect_to_login_page_on_error(error_msg="Impossible to decode user infos.", request=request)

    if "sub" not in user_data:
        # 'sub' is the unique identifier from Inclusion Connect, we need that to match a user later on.
        return _redirect_to_login_page_on_error(error_msg="Sub parameter missing.", request=request)

    is_successful = True
    ic_user_data = InclusionConnectUserData.from_user_info(user_data)
    ic_session_email = ic_session.get("user_email")

    if ic_session_email and ic_session_email != ic_user_data.email:
        error = (
            "L’adresse e-mail que vous avez utilisée pour vous connecter avec Inclusion Connect "
            f"({ic_user_data.email}) "
            f"est différente de celle que vous avez indiquée précédemment ({ic_session_email})."
        )
        messages.error(request, error)
        is_successful = False

    prescriber_session_data = request.session.get(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)

    # User coming from the prescriber signup path.
    if ic_session["user_kind"] == KIND_PRESCRIBER and prescriber_session_data:
        # Prescriber signup path callback.
        # Forbid signup for non prescribers
        non_prescriber_user_exists = User.objects.filter(email=ic_user_data.email, is_prescriber=False).exists()

        if non_prescriber_user_exists:
            error = (
                "Un compte non prescripteur existe déjà avec cette adresse e-mail. Besoin d'aide ? "
                f"<a href='{settings.ITOU_ASSISTANCE_URL}/#support' target='_blank'>Contactez-nous</a>."
            )
            messages.error(request, mark_safe(error))
            is_successful = False

    if not is_successful:
        logout_url_params = {
            "redirect_url": ic_session["previous_url"],
        }
        next_url = f"{reverse('inclusion_connect:logout')}?{urlencode(logout_url_params)}"
        return HttpResponseRedirect(next_url)

    try:
        user, _ = ic_user_data.create_or_update_user()
    except TooManyKindsException as e:
        messages.info(request, "Ce compte existe déjà, veuillez vous connecter.")
        if e.user.is_job_seeker:
            return HttpResponseRedirect(reverse("login:job_seeker"))
        if e.user.is_siae_staff:
            return HttpResponseRedirect(reverse("login:siae_staff"))
        if e.user.is_labor_inspector:
            return HttpResponseRedirect(reverse("login:labor_inspector"))

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
        "post_logout_redirect_uri": get_absolute_url(post_logout_redirect_url),
    }
    complete_url = f"{constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT}?{urlencode(params)}"
    return HttpResponseRedirect(complete_url)
