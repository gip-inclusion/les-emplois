import logging

from allauth.account.adapter import get_adapter
from allauth.socialaccount.helpers import complete_social_login, render_authentication_error
from allauth.socialaccount.models import SocialLogin
from allauth.socialaccount.providers.base import AuthError, ProviderException
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from allauth.socialaccount.providers.oauth2.views import OAuth2CallbackView, OAuth2LoginView
from allauth.utils import get_request_param
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.urls import reverse
from requests import RequestException

from itou.allauth_adapters.peamu.adapter import PEAMUOAuth2Adapter


logger = logging.getLogger(__name__)


class PEAMUOAuth2CallbackView(OAuth2CallbackView):
    def dispatch(self, request, *args, **kwargs):
        """
        This overloading is necessary to manage the case
        when the user clicks on "Cancel" once on the "Mire de connexion PE Connect".
        (╯°□°)╯︵ ┻━┻

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
                logger.error("Unknown error in PEAMU dispatch.")
            return render_authentication_error(request, self.adapter.provider_id, error=error)
        app = self.adapter.get_provider().app
        client = self.get_client(self.request, app)
        try:
            access_token = self.adapter.get_access_token_data(request, app, client)
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
            logger.error("Unknown error in PEAMU dispatch with exception '%s'.", e)
            return render_authentication_error(request, self.adapter.provider_id, exception=e)


def redirect_to_dashboard_view(request):
    return HttpResponseRedirect(
        get_adapter().get_login_redirect_url(request) if request.user.is_authenticated else reverse("account_login")
    )


oauth2_login = OAuth2LoginView.adapter_view(PEAMUOAuth2Adapter)
oauth2_callback = PEAMUOAuth2CallbackView.adapter_view(PEAMUOAuth2Adapter)
