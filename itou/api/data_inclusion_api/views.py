from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema
from rest_framework import exceptions, generics
from rest_framework.permissions import BasePermission

from itou.api.auth import ServiceAccount, ServiceTokenAuthentication
from itou.api.data_inclusion_api import enums, serializers
from itou.api.models import ServiceToken
from itou.companies.models import Company
from itou.nexus.enums import Service
from itou.prescribers.models import PrescriberOrganization
from itou.utils.auth import LoginNotRequiredMixin


class DataInclusionPermission(BasePermission):
    def has_permission(self, request, view):
        return (
            isinstance(request.user, ServiceAccount)
            and isinstance(request.auth, ServiceToken)
            and request.auth.service == Service.DATA_INCLUSION
        )


@extend_schema(
    responses=PolymorphicProxySerializer(
        component_name="DataInclusionStructure",
        serializers={
            "orga": serializers.PrescriberOrgStructureSerializer,
            "siae": serializers.CompanySerializer,
        },
        resource_type_field_name="type",
        many=True,
    )
)
class DataInclusionStructureView(LoginNotRequiredMixin, generics.ListAPIView):
    """
    # API au format data.inclusion

    Sérialisation des données SIAEs et organisations dans le schéma data⋅inclusion.

    Cf https://github.com/gip-inclusion/data-inclusion-schema

    Les données SIAEs et les données organisations (prescripteurs et orienteurs) sont
    accessibles via le même point d'entrée. Il est nécessaire de préciser le paramètre
    `type` dans la requête, pour obtenir soit les SIAEs (`type=siae`), soit les
    organisations (`type=orga`).
    """

    authentication_classes = [ServiceTokenAuthentication]

    permission_classes = [DataInclusionPermission]

    def list(self, request, *args, **kwargs):
        unsafe_type_str = self.request.query_params.get("type")

        if unsafe_type_str is None:
            raise exceptions.ValidationError("Le paramètre `type` est obligatoire.")
        elif unsafe_type_str not in list(enums.StructureTypeStr):
            raise exceptions.ValidationError("La valeur du paramètre `type` doit être `siae` ou `orga`.")

        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        qs = {
            enums.StructureTypeStr.ORGA: PrescriberOrganization.objects.all(),
            enums.StructureTypeStr.SIAE: Company.objects.active(),
        }[self.request.query_params.get("type")]
        return qs.order_by("created_at", "pk")

    def get_serializer_class(self):
        return {
            enums.StructureTypeStr.ORGA: serializers.PrescriberOrgStructureSerializer,
            enums.StructureTypeStr.SIAE: serializers.CompanySerializer,
        }[self.request.query_params.get("type")]
