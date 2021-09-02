from rest_framework import serializers

from itou.common_apps.address.models import AddressMixin
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
    cree_le = serializers.DateTimeField(source="created_at", label="Date de création")
    mis_a_jour_le = serializers.DateTimeField(source="updated_at", label="Date de mise à jour")
    type = serializers.ChoiceField(source="kind", label="Type de SIAE", choices=Siae.KIND_CHOICES)
    ville = serializers.CharField(source="city", label="Ville où se trouve la SIAE")
    code_postal = serializers.CharField(source="post_code", label="Code postal de la SIAE")
    addresse_line_1 = serializers.CharField(source="address_line_1", label="1ère ligne d’adresse de la SIAE")
    addresse_line_2 = serializers.CharField(source="address_line_2", label="2nde ligne d’adresse de la SIAE")
    departement = serializers.CharField(source="department", label="Le département où se trouve la SIAE")
    raison_sociale = serializers.CharField(source="name", label="Raison sociale de la SIAE")
    enseigne = serializers.CharField(source="display_name", label="Nom de la SIAE utilisé pour affichage")
    bloque_candidatures = serializers.BooleanField(source="block_job_applications", label="Est-ce que cette SIAE bloque toute les candidatures ?")
    postes = _JobDescriptionSerializer(source="job_description_through", many=True, label="Les postes disponibles")

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
            "postes",
        ]
        read_only_fields = fields
