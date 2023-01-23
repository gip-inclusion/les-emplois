import requests
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.oauth2.views import OAuth2Adapter
from django.conf import settings

from itou.allauth_adapters.peamu.client import PEAMUOAuth2Client
from itou.allauth_adapters.peamu.provider import PEAMUProvider
from itou.users import enums as users_enums
from itou.utils import constants as global_constants


class PEAMUSocialAccountAdapter(DefaultSocialAccountAdapter):
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        user.kind = users_enums.UserKind.JOB_SEEKER
        user.identity_provider = users_enums.IdentityProvider.PE_CONNECT
        nir = request.session.get(global_constants.ITOU_SESSION_NIR_KEY)
        if nir:
            user.nir = nir
        return user


class PEAMUOAuth2Adapter(OAuth2Adapter):
    provider_id = PEAMUProvider.id
    client_class = PEAMUOAuth2Client

    authorize_url = f"{settings.PEAMU_AUTH_BASE_URL}/connexion/oauth2/authorize"
    access_token_url = f"{settings.PEAMU_AUTH_BASE_URL}/connexion/oauth2/access_token"
    profile_url = f"{settings.API_ESD['BASE_URL']}/peconnect-individu/v1/userinfo"
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}

    def complete_login(self, request, app, token, **kwargs):
        id_token = token.token
        headers = {"Authorization": f"Bearer {id_token}"}
        response = requests.get(self.profile_url, params=None, headers=headers, timeout=settings.REQUESTS_TIMEOUT)
        response.raise_for_status()
        extra_data = response.json()
        extra_data["id_token"] = id_token
        login = self.get_provider().sociallogin_from_response(request, extra_data)
        return login
