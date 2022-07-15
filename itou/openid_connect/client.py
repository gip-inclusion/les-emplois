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

from .models import OIDConnectState, TooManyKindsException


logger = logging.getLogger(__name__)


@dataclasses.dataclass
class OIDConnectSession:
    token: str = None
    state: str = None
    previous_url: str = None
    next_url: str = None
    user_email: str = None
    user_kind: str = None
    request: str = None
    key: str = None


class OIDProvider:
    state_class: OIDConnectState
    session_class: OIDConnectSession
    base_url: str
    authorize_additional_kwargs: dict[str, str]
    client_id: str
    scopes: str
    url_namespace: str
    session_key: str
    timeout: int

    @property
    def callback_url(self):
        return get_absolute_url(reverse(f"{self.url_namespace}:callback"))


class OIDConnectClient:
    provider: OIDProvider

    def initialize_session(self, request):
        user_kind = request.GET.get("user_kind")
        previous_url = request.GET.get("previous_url", reverse("home:hp"))
        next_url = request.GET.get("next_url")
        login_hint = request.GET.get("login_hint")
        session = OIDConnectSession(
            previous_url=previous_url,
            next_url=next_url,
            user_kind=user_kind,
            user_email=login_hint,
        )
        request.session[self.provider.session_key] = dataclasses.asdict(session)
        request.session.has_changed = True
        return request.session[self.provider.session_key]

    def authorize(self, request):
        session = self.initialize_session(request)

        data = {
            "response_type": "code",
            "client_id": self.provider.client_id,
            "redirect_uri": self.provider.callback_url,
            "scope": self.provider.scopes,
            "state": self.provider.state_class.create_signed_csrf_token(),
            "nonce": crypto.get_random_string(length=12),
        }
        if session["user_email"]:
            data["login_hint"] = session["user_email"]
        return HttpResponseRedirect(f"{self.provider.base_url}/authorize?{urlencode(data)}")

    def redirect_on_error(self, error_msg, request):
        if request:
            messages.error(request, "Une erreur technique est survenue. Merci de recommencer.")
        logger.error(error_msg)
        return HttpResponseRedirect(reverse("login:job_seeker"))  # TODO(alaurent) depends on provider ?

    def callback(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")
        if code is None or not self.provider.state_class.is_valid(state):
            return self.redirect_on_error(error_msg="Missing code or invalid state.", request=request)

        ic_session = request.session[self.provider.session_key]

        data = {
            "client_id": self.provider.client_id,
            "client_secret": self.provider.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.provider.callback_url,
        }

        response = httpx.post(
            f"{self.provider.base_url}/token",
            data=data,
            timeout=self.provider.timeout,
        )

        if response.status_code != 200:
            return self.redirect_on_error(error_msg="Impossible to get IC token.", request=request)

        # Contains access_token, token_type, expires_in, id_token
        token_data = response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return self.redirect_on_error(error_msg="Access token field missing.", request=request)

        # Keep token_data["id_token"] to logout from IC.
        # At this step, we can update the user's fields in DB and create a session if required.
        ic_session["token"] = token_data["id_token"]
        ic_session["state"] = state
        request.session.modified = True

        # A token has been provided so it's time to fetch associated user infos
        # because the token is only valid for 5 seconds.
        response = httpx.get(
            f"{self.provider.base_url}/userinfo",
            params={"schema": "openid"},
            headers={"Authorization": "Bearer " + access_token},
            timeout=self.provider.timeout,
        )
        if response.status_code != 200:
            return self.redirect_on_error(error_msg="Impossible to get user infos.", request=request)

        try:
            user_data = json.loads(response.content.decode("utf-8"))
        except json.decoder.JSONDecodeError:
            return self.redirect_on_error(error_msg="Impossible to decode user infos.", request=request)

        if "sub" not in user_data:
            # 'sub' is the unique identifier from Inclusion Connect, we need that to match a user later on.
            return self.redirect_on_error(error_msg="Sub parameter missing.", request=request)

        is_successful = True
        ic_user_data = self.provider.user_data_class.from_user_info(user_data)
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
