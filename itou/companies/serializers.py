from rest_framework import serializers

from itou.companies.enums import CompanyKind
from itou.companies.models import Siae, SiaeJobDescription


class _JobDescriptionSerializer(serializers.ModelSerializer):
    rome = serializers.CharField(source="appellation.rome", label="Code ROME du poste")
    recrutement_ouvert = serializers.CharField(source="is_active", label="Ce poste est-il encore ouvert ?")
    appellation_modifiee = serializers.CharField(source="custom_name", label="Nom personnalisé")
    cree_le = serializers.DateTimeField(source="created_at", label="Date de création")
    mis_a_jour_le = serializers.DateTimeField(source="updated_at", label="Date de mise à jour")

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
    type = serializers.ChoiceField(source="kind", label="Type de SIAE", choices=CompanyKind.choices)
    ville = serializers.CharField(source="city", label="Ville où se trouve la SIAE")
    code_postal = serializers.CharField(source="post_code", label="Code postal de la SIAE")
    site_web = serializers.CharField(source="website", label="URL du site web de la SIAE")
    addresse_ligne_1 = serializers.CharField(source="address_line_1", label="1ère ligne d’adresse de la SIAE")
    addresse_ligne_2 = serializers.CharField(source="address_line_2", label="2nde ligne d’adresse de la SIAE")
    departement = serializers.CharField(source="department", label="Le département où se trouve la SIAE")
    raison_sociale = serializers.CharField(source="name", label="Raison sociale de la SIAE")
    enseigne = serializers.CharField(source="display_name", label="Nom de la SIAE utilisé pour affichage")
    bloque_candidatures = serializers.BooleanField(
        source="block_job_applications", label="Est-ce que cette SIAE bloque toute les candidatures ?"
    )
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
            "site_web",
            "description",
            "bloque_candidatures",
            "addresse_ligne_1",
            "addresse_ligne_2",
            "code_postal",
            "ville",
            "departement",
            "postes",
        ]
        read_only_fields = fields
