from allauth.account.models import EmailAddress
from allauth.socialaccount import providers
from allauth.socialaccount.app_settings import QUERY_EMAIL
from allauth.socialaccount.providers.base import ProviderAccount
from allauth.socialaccount.providers.oauth2.provider import OAuth2Provider
from django.conf import settings


class Scope(object):
    EMAIL = "email"
    PROFILE = "profile"


class PEAMUAccount(ProviderAccount):
    def get_profile_url(self):
        return self.account.extra_data.get("link")

    def get_avatar_url(self):
        return self.account.extra_data.get("picture")

    def to_str(self):
        dflt = super(PEAMUAccount, self).to_str()
        return self.account.extra_data.get("name", dflt)


class PEAMUProvider(OAuth2Provider):
    id = "peamu"
    name = "PEAMU"
    account_class = PEAMUAccount

    def get_default_scope(self):
        scope = [Scope.PROFILE]
        if QUERY_EMAIL:
            scope.append(Scope.EMAIL)
        scope += [
            "openid",
            "api_peconnect-individuv1",
            f"application_{settings.SOCIALACCOUNT_PROVIDERS['peamu']['APP']['client_id']}",
        ]
        return scope

    def get_auth_params(self, request, action):
        ret = super().get_auth_params(request, action)
        # Breaks anyway.
        # if action == AuthAction.REAUTHENTICATE:
        #     ret["prompt"] = "select_account consent"
        # if True:
        #     ret["prompt"] = "select_account"
        ret["realm"] = "/individu"
        return ret

    def extract_uid(self, data):
        return str(data["sub"])

    def extract_common_fields(self, data):
        # OK this is actually called.
        return dict(
            email=data.get("email"),
            last_name=data.get("family_name"),
            first_name=data.get("given_name"),
            # is_job_seeker=True,  # did not work :-(
        )

    def extract_email_addresses(self, data):
        ret = []
        email = data.get("email")
        if email and data.get("verified_email"):
            ret.append(EmailAddress(email=email, verified=True, primary=True))
        return ret


providers.registry.register(PEAMUProvider)
