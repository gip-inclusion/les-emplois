from allauth.socialaccount import providers
from django.apps import AppConfig

from itou.allauth_adapters.peamu.provider import PEAMUProvider


class AllauthAdaptersAppConfig(AppConfig):
    name = "itou.allauth_adapters"


# Register before allauth apps, to prevent a migration in SocialAccount.provider choices.
providers.registry.register(PEAMUProvider)
