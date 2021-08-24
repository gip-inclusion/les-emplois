import logging

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import pagination, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.filters import OrderingFilter

from itou.cities.models import City
from itou.siaes.models import Siae
from itou.siaes.serializers import SiaeSerializer


logger = logging.getLogger("api_drf")
CODE_INSEE_PARAM_NAME = "code_insee"
DISTANCE_PARAM_NAME = "distance_max_km"


class SiaePagination(pagination.PageNumberPagination):
    """
    Pole Emploi requests a per-page pagination, with the possibility to customize the page size per-request.
    Initial values are conservatives, they could be increased if the load allows it
    https://www.django-rest-framework.org/api-guide/pagination/#pagenumberpagination
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


class SiaeViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SiaeSerializer
    pagination_class = SiaePagination
    filter_backends = [OrderingFilter]
    ordering_fields = [
        "block_job_applications",
        "type",
        "city",
        "post_code",
        "department",
        "siret",
        "raison_sociale",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at", "-updated_at"]

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
            OpenApiParameter(name=CODE_INSEE_PARAM_NAME, description="Filter by city", required=False, type=str),
            OpenApiParameter(name=DISTANCE_PARAM_NAME, description="Filter by distance", required=False, type=str),
        ],
        responses={200: SiaeSerializer, 404: OpenApiTypes.OBJECT},
        examples=[
            NOT_FOUND_RESPONSE,
        ],
    )
    def list(self, request):
        # your non-standard behaviour
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
        if params.get(DISTANCE_PARAM_NAME) and code_insee:
            distance_filter = int(params.get(DISTANCE_PARAM_NAME))
            if distance_filter < 0 or distance_filter > 100:
                raise ValidationError(f"{DISTANCE_PARAM_NAME} doit être entre 0 et 100")

            try:
                city = City.objects.get(code_insee=code_insee)
                return queryset.within(city.coords, distance_filter)
            except City.DoesNotExist:
                # Ensure the error comes from a missing city, which may not be that clear
                # with get_object_or_404
                raise NotFound(f"Pas de ville avec pour code_insee {code_insee}")
        else:
            raise ValidationError(f"{CODE_INSEE_PARAM_NAME} et {DISTANCE_PARAM_NAME} sont des paramètres obligatoires")

        return queryset
