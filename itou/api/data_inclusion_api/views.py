from rest_framework import generics

from itou.api.data_inclusion_api import serializers
from itou.siaes.models import Siae


class DataInclusionStructureView(generics.ListAPIView):
    """
    # API SIAEs au format data.inclusion

    Sérialisation des données SIAEs dans le schéma data.inclusion.

    Cf https://github.com/betagouv/data-inclusion-schema
    """

    queryset = Siae.objects.active().order_by("created_at").select_related("convention")
    serializer_class = serializers.DataInclusionStructureSerializer
