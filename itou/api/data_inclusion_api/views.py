from django.db.models import Count, OuterRef, Subquery
from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema
from rest_framework import authentication, exceptions, generics

from itou.api.data_inclusion_api import enums, serializers
from itou.companies.models import Company
from itou.prescribers.models import PrescriberOrganization


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
class DataInclusionStructureView(generics.ListAPIView):
    """
    # API au format data.inclusion

    Sérialisation des données SIAEs et organisations dans le schéma data.inclusion.

    Cf https://github.com/betagouv/data-inclusion-schema

    Les données SIAEs et les données organisations (prescripteurs et orienteurs) sont
    accessibles via le même point d'entrée. Il est nécessaire de préciser le paramètre
    `type` dans la requête, pour obtenir soit les SIAEs (`type=siae`), soit les
    organisations (`type=orga`).
    """

    authentication_classes = [
        authentication.TokenAuthentication,
        authentication.SessionAuthentication,
    ]

    def list(self, request, *args, **kwargs):
        unsafe_type_str = self.request.query_params.get("type")

        if unsafe_type_str is None:
            raise exceptions.ValidationError("Le paramètre `type` est obligatoire.")
        elif unsafe_type_str not in list(enums.StructureTypeStr):
            raise exceptions.ValidationError("La valeur du paramètre `type` doit être `siae` ou `orga`.")

        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        valid_type_str = self.request.query_params.get("type")

        qs_by_structure_type_str = {
            enums.StructureTypeStr.ORGA: PrescriberOrganization.objects.all(),
            enums.StructureTypeStr.SIAE: Company.objects.active()
            .select_related("convention")
            .annotate(
                same_siret_count=Subquery(
                    Company.objects.filter(siret=OuterRef("siret"))
                    .values("siret")
                    .annotate(count=Count("pk"))
                    .values("count")
                )
            ),
        }

        # * ordered by ascending creation date : if any instances are added during the querying
        # of the endpoint, they will appear in the last page.
        # * ordered by pk : given that some instances share the same creation date, it ensures
        # repeatable order between page evaluation
        return qs_by_structure_type_str[valid_type_str].order_by("created_at", "pk")

    def get_serializer_class(self):
        valid_type_str = self.request.query_params.get("type")

        serializer_class_by_structure_type_str = {
            enums.StructureTypeStr.ORGA: serializers.PrescriberOrgStructureSerializer,
            enums.StructureTypeStr.SIAE: serializers.CompanySerializer,
        }

        return serializer_class_by_structure_type_str[valid_type_str]
