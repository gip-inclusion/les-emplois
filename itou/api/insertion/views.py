from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics

from itou.api.auth import DoraTokenAuthentication
from itou.api.insertion.serializers import OrientationRequestSerializer, OrientationSerializer
from itou.insertion.models import Orientation, OrientationProcessLink
from itou.utils.auth import LoginNotRequiredMixin


orientations_view_description = """
# API des orientations

Cette API est à l’usage exclusif du service [DORA](https://dora.inclusion.gouv.fr).

Elle retoure une liste d’orientations reçues par une structure porteuse de services.
Il est nécessaire de passer dans le corps de la requête (formulaire POST ou json) une valeur pour `structure_uid`
qui est l’identifiant data·inclusion de la structure.

## Permissions

L’utilisation de cette API nécessite un token d’autorisation.
"""


@extend_schema_view(
    post=extend_schema(
        operation_id="orientations",
        parameters=[
            OpenApiParameter("page", OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter("page_size", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
        request=OrientationRequestSerializer,
        responses={
            200: OrientationSerializer,
        },
        description=orientations_view_description,
    )
)
class OrientationsView(LoginNotRequiredMixin, generics.GenericAPIView):
    authentication_classes = (DoraTokenAuthentication,)
    serializer_class = OrientationSerializer
    queryset = (
        Orientation.objects.all()
        .select_related(
            "beneficiary",
            "beneficiary__jobseeker_profile",
            "service",
            "sender",
            "sender_prescriber_organization",
            "sender_company",
        )
        .order_by("created_at", "pk")
    )

    @staticmethod
    def _add_process_link(orientations):
        for orientation in orientations:
            process_link = OrientationProcessLink.objects.create(orientation=orientation)
            orientation.new_process_link = process_link.process_link
        return orientations

    def list(self, request, *args, **kwargs):
        """
        Write our own version of ListModelMixin.list() to be able to apply _add_process_link()
        to the current page's orientations only.
        """
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(self._add_process_link(page), many=True)
            return self.get_paginated_response(serializer.data)

    def filter_queryset(self, queryset):
        validated_data = self.request_serializer.validated_data
        queryset = queryset.filter(service__structure__uid=validated_data["structure_uid"])
        return queryset

    def post(self, request, *args, **kwargs):
        self.request_serializer = OrientationRequestSerializer(data=request.data)
        self.request_serializer.is_valid(raise_exception=True)
        return self.list(request, *args, **kwargs)
