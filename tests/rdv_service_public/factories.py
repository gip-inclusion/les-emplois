import datetime

import factory
from django.utils import timezone

from itou.rdv_service_public.models import OAuthToken
from tests.users.factories import EmployerFactory


class OAuthTokenFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OAuthToken

    user = factory.SubFactory(EmployerFactory)
    access_token = factory.Sequence(lambda n: f"access-token-{n}")
    refresh_token = factory.Sequence(lambda n: f"refresh-token-{n}")
    expires_at = factory.LazyFunction(lambda: timezone.now() + datetime.timedelta(hours=2))
    rdv_service_public_agent_id = factory.Sequence(int)
