import json
import logging
from urllib.parse import unquote

import httpx
from allauth.account.adapter import get_adapter
from django.conf import settings  # TODO: move to itou.prescribers.constants
from django.contrib import messages
from django.contrib.auth import login
from django.core import signing
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils import crypto
from django.utils.http import urlencode

from itou.utils.urls import get_absolute_url
from itou.www.signup.forms import PrescriberPoleEmploiUserSignupForm, PrescriberUserSignupBaseForm

from .constants import (  # INCLUSION_CONNECT_SCOPES,
    INCLUSION_CONNECT_CLIENT_ID,
    INCLUSION_CONNECT_CLIENT_SECRET,
    INCLUSION_CONNECT_ENDPOINT_AUTHORIZE,
    INCLUSION_CONNECT_ENDPOINT_LOGOUT,
    INCLUSION_CONNECT_ENDPOINT_TOKEN,
    INCLUSION_CONNECT_ENDPOINT_USERINFO,
    INCLUSION_CONNECT_SESSION_STATE,
    INCLUSION_CONNECT_SESSION_TOKEN,
)
from .models import InclusionConnectState, InclusionConnectUserData, create_or_update_user, userinfo_to_user_model_dict


logger = logging.getLogger(__name__)


def _redirect_to_login_page_on_error(error_msg, request=None):
    if request:
        messages.error(request, "Une erreur technique est survenue. Merci de recommencer.")
    logger.error(error_msg)
    return HttpResponseRedirect(reverse("login:job_seeker"))


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
        "from": "emplois",  # Display a "Les emplois" logo on the connection page.
    }
    if request.GET.get("login_hint"):
        data["login_hint"] = request.GET.get("login_hint")
    url = INCLUSION_CONNECT_ENDPOINT_AUTHORIZE
    return HttpResponseRedirect(f"{url}?{urlencode(data)}")


def inclusion_connect_callback(request):  # pylint: disable=too-many-return-statements
    # TODO: major refactor!
    code = request.GET.get("code")
    state = request.GET.get("state")
    if code is None or not state_is_valid(state):
        return _redirect_to_login_page_on_error(error_msg="Missing code or invalid state.", request=request)

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
        return _redirect_to_login_page_on_error(error_msg="Impossible to get IC token.", request=request)

    # Contains access_token, token_type, expires_in, id_token
    token_data = response.json()

    access_token = token_data.get("access_token")
    if not access_token:
        return _redirect_to_login_page_on_error(error_msg="Access token field missing.", request=request)

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
        return _redirect_to_login_page_on_error(error_msg="Impossible to get user infos.", request=request)

    try:
        user_data = json.loads(response.content.decode("utf-8"))
    except json.decoder.JSONDecodeError:
        return _redirect_to_login_page_on_error(error_msg="Impossible to decode user infos.", request=request)

    if "sub" not in user_data:
        # 'sub' is the unique identifier from Inclusion Connect, we need that to match a user later on.
        return _redirect_to_login_page_on_error(error_msg="Sub parameter missing.", request=request)

    # email_verified = user_data.get("email_verified")
    # TODO: error if email_verified is False
    ic_user_data = InclusionConnectUserData(**userinfo_to_user_model_dict(user_data))

    # User comes from prescriber signup path.
    # Add user to organization if any.
    prescriber_session_data = request.session.get(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
    next_url = None
    if prescriber_session_data:
        # Prescriber signup path callback.
        form_data = {
            "email": ic_user_data.email,
            "first_name": ic_user_data.first_name,
            "last_name": ic_user_data.last_name,
        }
        org_kind = prescriber_session_data.get("kind")
        if org_kind == "PE":
            form = PrescriberPoleEmploiUserSignupForm(data=form_data)
        else:
            form = PrescriberUserSignupBaseForm(data=form_data)

        if form.is_valid():
            user = form.save()
            if org_kind:
                next_url = reverse("signup:prescriber_join_org")
        else:
            for _, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)

            params = {
                INCLUSION_CONNECT_SESSION_TOKEN: token_data["id_token"],
                INCLUSION_CONNECT_SESSION_STATE: state,
                "redirect_url": prescriber_session_data["url_history"][-1],
            }
            next_url = f"{reverse('inclusion_connect:logout')}?{urlencode(params)}"
            return HttpResponseRedirect(next_url)
    else:
        # Other path.
        user, _ = create_or_update_user(ic_user_data)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    next_url = next_url or get_adapter(request).get_login_redirect_url(request)

    # Keep token_data["id_token"] to logout from FC
    # At this step, we can update the user's fields in DB and create a session if required
    request.session[INCLUSION_CONNECT_SESSION_TOKEN] = token_data["id_token"]
    request.session[INCLUSION_CONNECT_SESSION_STATE] = state
    request.session.modified = True

    return HttpResponseRedirect(next_url)


def inclusion_connect_logout(request):
    id_token = request.GET.get(INCLUSION_CONNECT_SESSION_TOKEN)
    state = request.GET.get(INCLUSION_CONNECT_SESSION_STATE)
    post_logout_redirect_url = request.GET.get("redirect_url", reverse("home:hp"))

    if not id_token:
        return JsonResponse({"message": "Le paramètre « id_token » est manquant."}, status=400)

    params = {
        "id_token_hint": id_token,
        "state": state,
    }
    url = INCLUSION_CONNECT_ENDPOINT_LOGOUT
    complete_url = f"{url}?{urlencode(params)}"
    # Logout user from IC with HTTPX to benefit from respx in tests
    # and to handle post logout redirection more easily.
    response = httpx.get(complete_url)
    if response.status_code != 302:
        logger.error("Error during IC logout. Status code: %s", response.status_code)
    return HttpResponseRedirect(post_logout_redirect_url)
