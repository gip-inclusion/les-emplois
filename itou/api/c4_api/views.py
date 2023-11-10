from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db.models import Prefetch
from rest_framework import authentication, exceptions, generics

from itou.api.c4_api.serializers import C4CompanySerializer
from itou.companies.enums import COMPANY_KIND_RESERVED
from itou.companies.models import Company, CompanyMembership


class C4APIUser(AnonymousUser):
    """
    Extension of `AnonymousUser` class:
    - Ensures that the `is_authenticated` property returns `True`.
    """

    @property
    def is_authenticated(self):
        return True


class C4Authentication(authentication.TokenAuthentication):
    def authenticate_credentials(self, key):
        if settings.C4_TOKEN is None or key != settings.C4_TOKEN:
            raise exceptions.AuthenticationFailed("Invalid token.")

        return C4APIUser(), None


class C4CompanyView(generics.ListAPIView):
    """API pour le Marché de l'inclusion"""

    authentication_classes = [C4Authentication]

    serializer_class = C4CompanySerializer

    def get_queryset(self):
        return (
            Company.objects.exclude(kind=COMPANY_KIND_RESERVED)
            .select_related("convention")
            .prefetch_related(
                Prefetch(
                    "members",
                    queryset=(
                        CompanyMembership.objects.filter(
                            is_admin=True,
                            is_active=True,
                            user__is_active=True,
                        )
                        .select_related("user")
                        .order_by("-joined_at")[:1]
                    ),
                    to_attr="admin",
                )
            )
            .order_by("id")
        )
