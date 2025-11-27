from django.db.models import Prefetch
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from itou.api.auth import ServiceAccount, ServiceTokenAuthentication
from itou.api.c4_api.serializers import C4CompanySerializer
from itou.api.models import ServiceToken
from itou.companies.enums import COMPANY_KIND_RESERVED
from itou.companies.models import Company, CompanyMembership
from itou.nexus.enums import Service
from itou.utils.auth import LoginNotRequiredMixin


class C4Permission(IsAuthenticated):
    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False

        return (
            isinstance(request.user, ServiceAccount)
            and isinstance(request.auth, ServiceToken)
            and request.auth.service == Service.MARCHE
        )


class C4CompanyView(LoginNotRequiredMixin, generics.ListAPIView):
    """API pour le Marché de l'inclusion"""

    authentication_classes = [ServiceTokenAuthentication]
    permission_classes = [C4Permission]

    serializer_class = C4CompanySerializer

    def get_queryset(self):
        return (
            Company.objects.exclude(kind=COMPANY_KIND_RESERVED)
            .select_related("convention")
            .prefetch_related(
                Prefetch(
                    "members",
                    queryset=(
                        CompanyMembership.objects.filter(is_admin=True)
                        .select_related("user")
                        .order_by("-joined_at")[:1]
                    ),
                    to_attr="admin",
                )
            )
            .order_by("id")
        )
