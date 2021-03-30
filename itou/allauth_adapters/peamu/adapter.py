import requests
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.oauth2.views import OAuth2Adapter
from django.conf import settings

from itou.allauth_adapters.peamu.provider import PEAMUProvider


class PEAMUSocialAccountAdapter(DefaultSocialAccountAdapter):
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        setattr(user, "is_job_seeker", True)
        return user


class PEAMUOAuth2Adapter(OAuth2Adapter):
    provider_id = PEAMUProvider.id

    authorize_url = f"{settings.PEAMU_AUTH_BASE_URL}/connexion/oauth2/authorize"
    access_token_url = f"{settings.PEAMU_AUTH_BASE_URL}/connexion/oauth2/access_token"
    profile_url = f"{settings.API_ESD_BASE_URL}/peconnect-individu/v1/userinfo"
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}

    def complete_login(self, request, app, token, **kwargs):
        id_token = token.token
        headers = {"Authorization": f"Bearer {id_token}"}
        resp = requests.get(self.profile_url, params=None, headers=headers, timeout=settings.REQUESTS_TIMEOUT)
        resp.raise_for_status()
        extra_data = resp.json()
        extra_data["id_token"] = id_token
        login = self.get_provider().sociallogin_from_response(request, extra_data)
        return login
