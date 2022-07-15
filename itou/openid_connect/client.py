import dataclasses

from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import crypto
from django.utils.http import urlencode

from itou.utils.urls import get_absolute_url

from .models import OIDConnectState


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
