from rest_framework import serializers

from itou.siaes.models import Siae, SiaeJobDescription


class _JobDescriptionSerializer(serializers.ModelSerializer):
    rome = serializers.CharField(source="appellation.rome")
    recrutement_ouvert = serializers.CharField(source="is_active")
    appellation_modifiee = serializers.CharField(source="custom_name")
    cree_le = serializers.DateTimeField(source="created_at")
    mis_a_jour_le = serializers.DateTimeField(source="updated_at")

    class Meta:
        model = SiaeJobDescription
        fields = [
            "id",
            "rome",
            "cree_le",
            "mis_a_jour_le",
            "recrutement_ouvert",
            "description",
            "appellation_modifiee",
        ]
        read_only_fields = fields


class SiaeSerializer(serializers.ModelSerializer):
    cree_le = serializers.DateTimeField(source="created_at")
    mis_a_jour_le = serializers.DateTimeField(source="updated_at")
    type = serializers.CharField(source="kind")
    ville = serializers.CharField(source="city")
    code_postal = serializers.CharField(source="post_code")
    addresse_line_1 = serializers.CharField(source="address_line_1")
    addresse_line_2 = serializers.CharField(source="address_line_2")
    departement = serializers.CharField(source="department")
    raison_sociale = serializers.CharField(source="name")
    enseigne = serializers.SerializerMethodField()
    bloque_candidatures = serializers.BooleanField(source="block_job_applications")
    candidatures = _JobDescriptionSerializer(source="job_description_through", many=True)

    class Meta:
        model = Siae
        fields = [
            "cree_le",
            "mis_a_jour_le",
            "siret",
            "type",
            "raison_sociale",
            "enseigne",
            "website",
            "description",
            "bloque_candidatures",
            "addresse_line_1",
            "addresse_line_2",
            "code_postal",
            "ville",
            "departement",
            "candidatures",
        ]
        read_only_fields = fields

    def get_enseigne(self, obj):
        return obj.display_name
