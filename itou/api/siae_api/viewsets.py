import logging

from django.db.models import Prefetch
from django_filters.filters import CharFilter, NumberFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend, FilterSet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.throttling import UserRateThrottle

from itou.cities.models import City
from itou.companies.models import Company, JobDescription

from .serializers import SiaeSerializer


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
        required=True,
        help_text="Filtre par code INSEE de la ville",
    )
    distance_max_km = NumberFilter(
        method=noop,  # Noop filter since filtering happens in filter_queryset method
        required=True,
        min_value=0,
        max_value=MAX_DISTANCE_RADIUS_KM,
        help_text=(
            "Filtre par rayon de recherche autour de la ville, en kilomètres. "
            f"Maximum {MAX_DISTANCE_RADIUS_KM} kilomètres."
        ),
    )

    def filter_queryset(self, queryset):
        filtered_queryset = super().filter_queryset(queryset)
        code_insee = self.form.cleaned_data["code_insee"]
        distance = self.form.cleaned_data["distance_max_km"]

        t = f"Les paramètres `{CODE_INSEE_PARAM_NAME}` et `{DISTANCE_FROM_CODE_INSEE_PARAM_NAME}` sont obligatoires."
        if distance and code_insee:
            try:
                city = City.objects.get(code_insee=code_insee)
                return filtered_queryset.within(city.coords, distance)
            except City.DoesNotExist:
                # Ensure the error comes from a missing city, which may not be that clear
                # with get_object_or_404
                raise NotFound(f"Pas de ville avec pour code_insee {code_insee}")
        else:
            raise ValidationError(t)


class RestrictedUserRateThrottle(UserRateThrottle):
    """
    Very restrictive rate limits

    Historical limitation, a company made a business of crawling this
    API and selling the data. The data is meant to be available to
    the public, for free.
    """

    rate = "12/minute"


class SiaeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    # Liste des SIAE

    La plateforme renvoie une liste de SIAE à proximité d’une ville (déterminée par son code INSEE)
    et dans un rayon de recherche en kilomètres autour du centre de cette ville.

    Les coordonnées des centres-villes sont issus de [https://geo.api.gouv.fr](https://geo.api.gouv.fr/)


    Chaque SIAE est accompagnée d’un certain nombre de métadonnées :

     - SIRET
     - Type
     - Raison Sociale
     - Enseigne
     - Site web
     - Description de la SIAE
     - Blocage de toutes les candidatures OUI/NON
     - Adresse de la SIAE
     - Complément d’adresse
     - Code Postal
     - Ville
     - Département

    Chaque SIAE peut proposer 0, 1 ou plusieurs postes. Pour chaque poste renvoyé, les métadonnées fournies sont :

     - Appellation ROME
     - Date de création
     - Date de modification
     - Recrutement ouvert OUI/NON
     - Description du poste
     - Appellation modifiée
     - Type de contrat
     - Nombre de postes ouverts
     - Lieu
     - Profil recherché
    """

    serializer_class = SiaeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = CompanyFilterSet
    ordering = ["id"]

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    # No permission is required on this API and everybody can query anything − it’s read-only.
    permission_classes = []
    throttling_classes = [RestrictedUserRateThrottle]

    queryset = Company.objects.prefetch_related(
        Prefetch(
            "job_description_through",
            queryset=(
                JobDescription.objects.filter(is_active=True)
                .select_related("appellation__rome", "location")
                .order_by("-updated_at", "-created_at")
            ),
        )
    )

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

    def get_queryset(self):
        # We only get to this point if permissions are OK
        queryset = super().get_queryset()

        try:
            return queryset.order_by("id")
        finally:
            # Tracking is currently done via user-agent header
            logger.info(
                "User-Agent: %s",
                self.request.headers.get("User-Agent"),
            )
