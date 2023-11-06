import logging

from django.db.models import Prefetch
from django_filters.filters import OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend, FilterSet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.exceptions import NotFound, ValidationError

from itou.cities.models import City
from itou.companies.models import Company, JobDescription
from itou.companies.serializers import SiaeSerializer


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


class SiaeOrderingFilter(FilterSet):
    # Mapping of the model property names -> query parameter names used to order the results:
    # - keys: the name of the property in the model in order to order the results
    # - values: the name of the ordering criterion in the query parameter
    # If you want to query https://some_api?o=cree_le, it will perform queryset.order_by("created_at")
    o = OrderingFilter(fields=SIAE_ORDERING_FILTER_MAPPING)


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
    """

    serializer_class = SiaeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = SiaeOrderingFilter
    ordering = ["id"]

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    # No permission is required on this API and everybody can query anything − it’s read-only.
    permission_classes = []

    queryset = Company.objects.prefetch_related(
        Prefetch(
            "job_description_through",
            queryset=(
                JobDescription.objects.filter(is_active=True)
                .select_related("appellation__rome")
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
    sort_description = """
Critère de tri.

On peut spécifier la direction de tri :
 - o=critère pour l’ordre croissant
 - o=-critère pour l’ordre décroissant
    """

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name=CODE_INSEE_PARAM_NAME, description="Filtre par code INSEE de la ville", required=True, type=str
            ),
            OpenApiParameter(
                name=DISTANCE_FROM_CODE_INSEE_PARAM_NAME,
                description=f"Filtre par rayon de recherche autour de la ville, en kilomètres. Maximum {MAX_DISTANCE_RADIUS_KM} kilomètres",  # noqa: E501
                required=True,
                type=str,
            ),
            OpenApiParameter(name="format", description="Format de sortie", required=False, enum=["json", "api"]),
            OpenApiParameter(
                name="o",
                description=sort_description,
                required=False,
                enum=SIAE_ORDERING_FILTER_MAPPING.values(),
            ),
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

        # Get (registered) query parameters filters
        queryset = self._filter_by_query_params(self.request, queryset)

        try:
            return queryset.order_by("id")
        finally:
            # Tracking is currently done via user-agent header
            logger.info(
                "User-Agent: %s",
                self.request.headers.get("User-Agent"),
            )

    def _filter_by_query_params(self, request, queryset):
        params = request.query_params
        code_insee = params.get(CODE_INSEE_PARAM_NAME)
        t = f"Les paramètres `{CODE_INSEE_PARAM_NAME}` et `{DISTANCE_FROM_CODE_INSEE_PARAM_NAME}` sont obligatoires."
        if params.get(DISTANCE_FROM_CODE_INSEE_PARAM_NAME) and code_insee:
            distance_filter = int(params.get(DISTANCE_FROM_CODE_INSEE_PARAM_NAME))
            if distance_filter < 0 or distance_filter > MAX_DISTANCE_RADIUS_KM:
                raise ValidationError(
                    f"Le paramètre `{DISTANCE_FROM_CODE_INSEE_PARAM_NAME}` doit être compris entre 0 et {MAX_DISTANCE_RADIUS_KM}."  # noqa: E501
                )

            try:
                city = City.objects.get(code_insee=code_insee)
                return queryset.within(city.coords, distance_filter)
            except City.DoesNotExist:
                # Ensure the error comes from a missing city, which may not be that clear
                # with get_object_or_404
                raise NotFound(f"Pas de ville avec pour code_insee {code_insee}")
        else:
            raise ValidationError(t)
