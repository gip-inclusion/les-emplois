from typing import Optional

from django.utils import text
from rest_framework import serializers

from itou.siaes.models import Siae


class DataInclusionStructureSerializer(serializers.ModelSerializer):
    """Serialize SIAE instance to the data.inclusion structure schema.

    Fields are based on https://github.com/betagouv/data-inclusion-schema.
    """

    id = serializers.CharField(source="public_id")
    typologie = serializers.ChoiceField(source="kind", choices=Siae.KIND_CHOICES)
    nom = serializers.CharField(source="display_name")
    rna = serializers.ReadOnlyField(default="")
    presentation_resume = serializers.SerializerMethodField()
    presentation_detail = serializers.SerializerMethodField()
    site_web = serializers.CharField(source="website")
    telephone = serializers.CharField(source="phone")
    courriel = serializers.CharField(source="email")
    code_postal = serializers.CharField(source="post_code")
    code_insee = serializers.ReadOnlyField(default="")
    commune = serializers.CharField(source="city")
    adresse = serializers.CharField(source="address_line_1")
    complement_adresse = serializers.CharField(source="address_line_2")
    date_maj = serializers.DateTimeField(source="updated_at")
    structure_parente = serializers.SerializerMethodField()

    class Meta:
        model = Siae
        fields = [
            "id",
            "typologie",
            "nom",
            "siret",
            "rna",
            "presentation_resume",
            "presentation_detail",
            "site_web",
            "telephone",
            "courriel",
            "code_postal",
            "code_insee",
            "commune",
            "adresse",
            "complement_adresse",
            "longitude",
            "latitude",
            "source",
            "date_maj",
            "structure_parente",
        ]
        read_only_fields = fields

    def get_presentation_resume(self, obj) -> str:
        return text.Truncator(obj.description).chars(280)

    def get_presentation_detail(self, obj) -> str:
        if len(obj.description) < 280:
            return ""
        return obj.description

    def get_structure_parente(self, obj) -> Optional[str]:
        if obj.source != Siae.SOURCE_USER_CREATED:
            return None

        try:
            structure_parente = Siae.objects.exclude(source=Siae.SOURCE_USER_CREATED).get(
                convention__asp_id=obj.asp_id
            )
        except (Siae.DoesNotExist, Siae.MultipleObjectsReturned):
            return None

        return structure_parente.public_id
