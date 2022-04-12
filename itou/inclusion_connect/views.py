import json
import logging
import random
import string
from urllib.parse import unquote

import httpx
from allauth.account.adapter import get_adapter
from django.conf import settings  # TODO: move to itou.prescribers.constants
from django.contrib import messages
from django.contrib.auth import login
from django.core import exceptions, signing
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import crypto
from django.utils.http import urlencode

from itou.prescribers.models import PrescriberOrganization
from itou.users.models import User
from itou.utils.urls import get_absolute_url
from itou.www.signup.forms import PrescriberPoleEmploiUserSignupForm, PrescriberUserSignupForm

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

    # Add user to organization if any.
    prescriber_session_data = request.session.get(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
    if prescriber_session_data:
        # A prescriber is trying to create an account with Inclusion Connect.
        kind = prescriber_session_data.get("kind")
        if kind:
            # User tries to create an account AND create or join an organization.
            # TODO: this may fail due to the CNILValidator.
            # Anyway, this is ugly! Split Signuo forms to avoid creating the user
            # with allauth's magic.
            fake_password = User.objects.make_random_password(length=20) + random.choice(string.punctuation)
            form_data = {
                "email": ic_user_data.email,
                "first_name": ic_user_data.first_name,
                "last_name": ic_user_data.last_name,
                "password1": fake_password,
                "password2": fake_password,
            }
            if kind == "PE":
                # User tries to join a Pôle emploi organization.
                pole_emploi_org_pk = prescriber_session_data.get("pole_emploi_org_pk")

                # Check session data.
                if not pole_emploi_org_pk or kind != PrescriberOrganization.Kind.PE.value:
                    raise exceptions.PermissionDenied

                pole_emploi_org = get_object_or_404(PrescriberOrganization, pk=pole_emploi_org_pk)
                form = PrescriberPoleEmploiUserSignupForm(data=form_data, pole_emploi_org=pole_emploi_org)
            else:
                form_kwargs = {
                    "authorization_status": prescriber_session_data["authorization_status"],
                    "kind": prescriber_session_data["kind"],
                    "prescriber_org_data": prescriber_session_data["prescriber_org_data"],
                }
                form = PrescriberUserSignupForm(data=form_data, **form_kwargs)
            if form.is_valid():
                user = form.save(request=request)
            else:
                for key, errors in form.errors.items():
                    messages.error(request, f"{key} : {errors.as_text()}")
                return HttpResponseRedirect(prescriber_session_data["url_history"][-1])
        else:
            # Create an "Orienteur" account (ie prescriber without organization).
            user, _ = create_or_update_user(ic_user_data)
    else:
        # User tries to login.
        user, _ = create_or_update_user(ic_user_data)

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    next_url = get_adapter(request).get_login_redirect_url(request)

    # Keep token_data["id_token"] to logout from FC
    # At this step, we can update the user's fields in DB and create a session if required
    request.session[INCLUSION_CONNECT_SESSION_TOKEN] = token_data["id_token"]
    request.session[INCLUSION_CONNECT_SESSION_STATE] = state
    request.session.modified = True

    return HttpResponseRedirect(next_url)


def inclusion_connect_logout(request):
    id_token = request.GET.get(INCLUSION_CONNECT_SESSION_TOKEN)
    state = request.GET.get(INCLUSION_CONNECT_SESSION_STATE)
    if not id_token:
        return JsonResponse({"message": "Le paramètre « id_token » est manquant."}, status=400)

    params = {
        "id_token_hint": id_token,
        "state": state,
        "post_logout_redirect_uri": get_absolute_url(reverse("home:hp")),
    }
    url = INCLUSION_CONNECT_ENDPOINT_LOGOUT
    complete_url = f"{url}?{urlencode(params)}"
    return HttpResponseRedirect(complete_url)
