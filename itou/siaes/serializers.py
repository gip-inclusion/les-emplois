from rest_framework import serializers

from itou.siaes.models import Siae, SiaeJobDescription


class _JobDescriptionSerializer(serializers.ModelSerializer):
    """
    Pour chaque poste renvoyé par « Les emplois de l’inclusion » à Pôle emploi
    les données à afficher sont les suivantes :

    Appellation ROME
    Date de création
    Date de modification
    Recrutement ouvert OUI/NON
    Description du poste
    Appellation modifiée
    """

    rome = serializers.CharField(source="appellation.rome")
    recrutement_ouvert = serializers.CharField(source="is_active")
    appellation_modifiee = serializers.CharField(source="custom_name")

    class Meta:
        model = SiaeJobDescription
        fields = [
            "id",
            "rome",
            "created_at",
            "updated_at",
            "recrutement_ouvert",
            "description",
            "appellation_modifiee",
        ]
        read_only_fields = fields


class SiaeSerializer(serializers.ModelSerializer):
    """
    « Les emplois de l’inclusion » renvoie une liste de SIAE.

    Chaque SIAE peut proposer 0, 1 ou plusieurs postes.

    Pour chaque SIAE renvoyée à Pôle emploi les données à afficher sont les suivantes :

    SIRET
    Type
    Raison Sociale
    Enseigne
    Site web
    Description de la SIAE
    Blocage de toutes les candidatures OUI/NON
    Adresse de la SIAE
    Complément d’adresse
    Code Postal
    Ville
    Département
    """

    type = serializers.CharField(source="kind")
    ville = serializers.CharField(source="city")
    raison_sociale = serializers.CharField(source="name")
    enseigne = serializers.SerializerMethodField()
    job_descriptions = _JobDescriptionSerializer(source="job_description_through", many=True)

    class Meta:
        model = Siae
        fields = [
            "siret",
            "type",
            "raison_sociale",
            "enseigne",
            "website",
            "description",
            "block_job_applications",
            "address_line_1",
            "address_line_2",
            "post_code",
            "ville",
            "department",
            "job_descriptions",
        ]
        read_only_fields = fields

    def get_enseigne(self, obj):
        return obj.display_name
