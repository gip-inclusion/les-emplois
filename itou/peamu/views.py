import requests
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.oauth2.views import OAuth2Adapter, OAuth2CallbackView, OAuth2LoginView

from .client import PEAMUOAuth2Client
from .provider import PEAMUProvider


class PEAMUOAuth2Adapter(OAuth2Adapter):
    provider_id = PEAMUProvider.id

    authorize_url = "https://authentification-candidat.pole-emploi.fr/connexion/oauth2/authorize"
    access_token_url = "https://authentification-candidat.pole-emploi.fr/connexion/oauth2/access_token"
    profile_url = "https://api.emploi-store.fr/partenaire/peconnect-individu/v1/userinfo"
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}

    def complete_login(self, request, app, token, **kwargs):
        id_token = token.token
        headers = {"Authorization": f"Bearer {id_token}"}
        resp = requests.get(self.profile_url, params=None, headers=headers)
        resp.raise_for_status()
        extra_data = resp.json()
        extra_data["id_token"] = id_token
        login = self.get_provider().sociallogin_from_response(request, extra_data)
        return login


class PEAMUSocialAccountAdapter(DefaultSocialAccountAdapter):
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        # did not work :-( user_field expects a string
        # user_field(user, 'is_job_seeker', True)
        setattr(user, "is_job_seeker", True)
        return user


class PEAMUOAuth2CallbackView(OAuth2CallbackView):
    """
    Required exclusively for injecting realm=/individu
    when requesting access token.
    (╯°□°)╯︵ ┻━┻
    """

    def get_client(self, request, app):
        """
        This whole method is unchanged except for the
        custom `PEAMUOAuth2Client` required to load the
        `params = {"realm": "/individu"}` hack.
        Original code visible here:
        https://github.com/pennersr/django-allauth/blob/6a6d3c618ab018234dde8701173093274710ee0a/allauth/socialaccount/providers/oauth2/views.py#L78
        """
        callback_url = self.adapter.get_callback_url(request, app)
        provider = self.adapter.get_provider()
        scope = provider.get_scope(request)
        client = PEAMUOAuth2Client(
            self.request,
            app.client_id,
            app.secret,
            self.adapter.access_token_method,
            self.adapter.access_token_url,
            callback_url,
            scope,
            scope_delimiter=self.adapter.scope_delimiter,
            headers=self.adapter.headers,
            basic_auth=self.adapter.basic_auth,
        )
        return client


oauth2_login = OAuth2LoginView.adapter_view(PEAMUOAuth2Adapter)
oauth2_callback = PEAMUOAuth2CallbackView.adapter_view(PEAMUOAuth2Adapter)
