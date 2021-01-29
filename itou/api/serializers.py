from rest_framework import serializers

from itou.siaes.models import Siae


class SiaeSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Siae
        fields = ["kind", "siret", "source"]
