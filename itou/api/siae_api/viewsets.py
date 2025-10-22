import logging

from django.db.models import Exists, OuterRef, Prefetch, Q
from django_filters.filters import CharFilter, ChoiceFilter, NumberFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend, FilterSet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.exceptions import NotFound, ValidationError

from itou.api.auth import DepartmentTokenAuthentication
from itou.api.siae_api.serializers import SiaeSerializer
from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS
from itou.companies.models import Company, JobDescription
from itou.utils.auth import LoginNotRequiredMixin


logger = logging.getLogger("api_drf")
CODE_INSEE_PARAM_NAME = "code_insee"
DISTANCE_FROM_CODE_INSEE_PARAM_NAME = "distance_max_km"
MAX_DISTANCE_RADIUS_KM = 100

SIAE_ORDERING_FILTER_MAPPING = {
    "block_job_applications": "bloque_candidatures",
    "kind": "type",
    "department": "departement",
    "post_code": "code_postal",
    "city": "ville",
    "siret": "siret",
    "name": "raison_sociale",
}


def noop(queryset, name, value):
    return queryset


class CompanyFilterSet(FilterSet):
    # Mapping of the model property names -> query parameter names used to order the results:
    # - keys: the name of the property in the model in order to order the results
    # - values: the name of the ordering criterion in the query parameter
    # If you want to query https://some_api?o=cree_le, it will perform queryset.order_by("created_at")
    o = OrderingFilter(
        fields=SIAE_ORDERING_FILTER_MAPPING,
        help_text="Critère de tri",
    )

    code_insee = CharFilter(
        method=noop,  # Noop filter since filtering happens in filter_queryset method
        help_text="Filtre par code INSEE de la ville. À utiliser avec `distance_max_km`.",
    )
    distance_max_km = NumberFilter(
        method=noop,  # Noop filter since filtering happens in filter_queryset method
        min_value=0,
        max_value=MAX_DISTANCE_RADIUS_KM,
        help_text=(
            "Filtre par rayon de recherche autour de la ville, en kilomètres. "
            f"Maximum {MAX_DISTANCE_RADIUS_KM} kilomètres. À utiliser avec `code_insee`."
        ),
    )

    departement = ChoiceFilter(
        field_name="department", choices=list(DEPARTMENTS.items()), help_text="Département de la structure"
    )

    postes_dans_le_departement = ChoiceFilter(
        choices=list(DEPARTMENTS.items()),
        help_text="Département d'un poste de la structure.",
        method="having_job_in_department",
    )

    def having_job_in_department(self, queryset, name, value):
        # Either a Job in one of the department cities
        # or a Job without city when the company department matches
        return queryset.filter(
            Exists(JobDescription.objects.filter(company=OuterRef("pk"), location__department=value))
            | (
                Q(department=value)
                & Exists(JobDescription.objects.filter(company=OuterRef("pk"), location__isnull=True))
            )
        )

    def filter_queryset(self, queryset):
        filtered_queryset = super().filter_queryset(queryset)
        code_insee = self.form.cleaned_data.get("code_insee")
        distance = self.form.cleaned_data.get("distance_max_km")
        department = self.form.cleaned_data.get("departement")
        jobs_in_department = self.form.cleaned_data.get("postes_dans_le_departement")

        if distance and code_insee:
            try:
                city = City.objects.get(code_insee=code_insee)
                return filtered_queryset.within(city.coords, distance)
            except City.DoesNotExist:
                # Ensure the error comes from a missing city, which may not be that clear
                # with get_object_or_404
                raise NotFound(f"Pas de ville avec pour code_insee {code_insee}")
        elif not (department or jobs_in_department):
            raise ValidationError(
                f"Les paramètres `{CODE_INSEE_PARAM_NAME}` et `{DISTANCE_FROM_CODE_INSEE_PARAM_NAME}` sont "
                "obligatoires si ni `departement` ni `postes_dans_le_departement` ne sont spécifiés."
            )
        # Here the department/job_department filters have been applied
        return filtered_queryset


class SiaeViewSet(LoginNotRequiredMixin, viewsets.mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    # Liste des SIAE

    La plateforme renvoie une liste de SIAE à proximité d’une ville (déterminée par son code INSEE)
    et dans un rayon de recherche en kilomètres autour du centre de cette ville.

    Les coordonnées des centres-villes sont issus de [https://geo.api.gouv.fr](https://geo.api.gouv.fr/)

    Chaque SIAE est accompagnée d’un certain nombre de métadonnées, et peut proposer 0, 1 ou plusieurs postes.
    Pour le détail des métadonnées des SIAE et de leur postes, voir plus bas dans la section Responses
    """

    serializer_class = SiaeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = CompanyFilterSet
    ordering = ["id"]

    # The authentication is mainly here to have some information on who uses our API
    authentication_classes = [DepartmentTokenAuthentication, TokenAuthentication, SessionAuthentication]
    # No permission is required on this API and everybody can query anything − it’s read-only.
    permission_classes = []

    queryset = Company.objects.prefetch_related(
        Prefetch(
            "job_description_through",
            queryset=(
                JobDescription.objects.filter(is_active=True)
                .select_related("appellation__rome", "location")
                .order_by("-updated_at", "-created_at")
            ),
        )
    ).order_by("pk")

    NOT_FOUND_RESPONSE = OpenApiExample(
        "Not Found",
        description="Not Found",
        value="Pas de ville avec pour code_insee 1234",
        response_only=True,
        status_codes=["404"],
    )

    @extend_schema(
        parameters=[
            OpenApiParameter(name="format", description="Format de sortie", required=False, enum=["json", "api"]),
        ],
        responses={200: SiaeSerializer, 404: OpenApiTypes.OBJECT},
        examples=[
            NOT_FOUND_RESPONSE,
        ],
    )
    def list(self, request):
        # we need this despite the default behavior because of the documentation annotations
        return super().list(request)
