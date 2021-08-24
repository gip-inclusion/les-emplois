import logging

# from django_filters.filters import OrderingFilter
# from django_filters import FilterSet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import filters, viewsets
from rest_framework.exceptions import NotFound, ValidationError

from itou.cities.models import City
from itou.siaes.models import Siae
from itou.siaes.serializers import SiaeSerializer


logger = logging.getLogger("api_drf")
CODE_INSEE_PARAM_NAME = "code_insee"
DISTANCE_FROM_CODE_INSEE_PARAM_NAME = "distance_max_km"


class SiaeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    # Liste des SIAE

    La plateforme renvoie une liste de SIAE à proximité d’une ville (déterminée par son code INSEE)
    et d’un rayon de recherche en kilomètres autour de cette ville.


    Chaque SIAE est accompagnée d’un certain nombre de métadonnées:

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
    filter_backend = [filters.OrderingFilter]
    ordering = ["-cree_le", "-mis_a_jour_le"]

    # No authentication is required on this API and everybody can query anything − it’s read-only.
    authentication_classes = []
    permission_classes = []

    NOT_FOUND_RESPONSE = OpenApiExample(
        "Not Found",
        description="Not Found",
        value="Pas de ville avec pour code_insee 1234",
        response_only=True,
        status_codes=["404"],
    )

    @extend_schema(
        parameters=[
            OpenApiParameter(name=CODE_INSEE_PARAM_NAME, description="Filtre par ville", required=False, type=str),
            OpenApiParameter(
                name=DISTANCE_FROM_CODE_INSEE_PARAM_NAME, description="Filtre par distance", required=False, type=str
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
        queryset = Siae.objects

        # Get (registered) query parameters filters
        queryset = self._filter_by_query_params(self.request, queryset)

        try:
            return queryset
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
            if distance_filter < 0 or distance_filter > 100:
                raise ValidationError(
                    f"Le paramètre `{DISTANCE_FROM_CODE_INSEE_PARAM_NAME}` doit être compris entre 0 et 100."
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

        return queryset
