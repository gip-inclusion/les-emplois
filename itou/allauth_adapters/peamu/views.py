from allauth.socialaccount.helpers import complete_social_login, render_authentication_error
from allauth.socialaccount.models import SocialLogin
from allauth.socialaccount.providers.base import AuthError, ProviderException
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from allauth.socialaccount.providers.oauth2.views import OAuth2CallbackView, OAuth2LoginView
from allauth.utils import get_request_param
from django.core.exceptions import PermissionDenied
from requests import RequestException

from itou.allauth_adapters.peamu.adapter import PEAMUOAuth2Adapter
from itou.allauth_adapters.peamu.client import PEAMUOAuth2Client


class PEAMUOAuth2CallbackView(OAuth2CallbackView):
    def get_client(self, request, app):
        """
        This overloading is required solely for injecting
        the non standard realm=/individu when requesting access token.
        (╯°□°)╯︵ ┻━┻

        This whole method is unchanged except for the
        custom `PEAMUOAuth2Client` required to load the
        `params = {"realm": "/individu"}` hack.
        Original code:
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

    def dispatch(self, request, *args, **kwargs):
        """
        This overloading is necessary to manage the case
        when the user clicks on "Cancel" once on the "Mire de connexion PE Connect".
        Original code:
        https://github.com/pennersr/django-allauth/blob/master/allauth/socialaccount/providers/oauth2/views.py#L113
        """
        if "error" in request.GET or "code" not in request.GET:
            # Distinguish cancel from error
            auth_error = request.GET.get("error", None)
            if auth_error == self.adapter.login_cancelled_error:
                error = AuthError.CANCELLED
            elif auth_error is None and "state" in request.GET:
                # This custom case happens when the user clicks "Cancel" on the
                # "Mire de connexion PE Connect".
                error = AuthError.CANCELLED
            else:
                error = AuthError.UNKNOWN
            return render_authentication_error(request, self.adapter.provider_id, error=error)
        app = self.adapter.get_provider().get_app(self.request)
        client = self.get_client(request, app)
        try:
            access_token = client.get_access_token(request.GET["code"])
            token = self.adapter.parse_token(access_token)
            token.app = app
            login = self.adapter.complete_login(request, app, token, response=access_token)
            login.token = token
            if self.adapter.supports_state:
                login.state = SocialLogin.verify_and_unstash_state(request, get_request_param(request, "state"))
            else:
                login.state = SocialLogin.unstash_state(request)
            return complete_social_login(request, login)
        except (PermissionDenied, OAuth2Error, RequestException, ProviderException) as e:
            return render_authentication_error(request, self.adapter.provider_id, exception=e)


oauth2_login = OAuth2LoginView.adapter_view(PEAMUOAuth2Adapter)
oauth2_callback = PEAMUOAuth2CallbackView.adapter_view(PEAMUOAuth2Adapter)
