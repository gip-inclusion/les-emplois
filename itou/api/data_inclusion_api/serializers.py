import re

from django.utils import text, timezone
from rest_framework import serializers

from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.enums import SiaeKind
from itou.siaes.models import Siae


class SiaeStructureSerializer(serializers.ModelSerializer):
    """Serialize SIAE instance to the data.inclusion structure schema.

    Fields are based on https://github.com/betagouv/data-inclusion-schema.
    """

    id = serializers.UUIDField(source="uid")
    typologie = serializers.ChoiceField(source="kind", choices=SiaeKind.choices)
    nom = serializers.CharField(source="display_name")
    siret = serializers.SerializerMethodField()
    rna = serializers.CharField(default="")
    presentation_resume = serializers.SerializerMethodField()
    presentation_detail = serializers.SerializerMethodField()
    site_web = serializers.CharField(source="website")
    telephone = serializers.CharField(source="phone")
    courriel = serializers.CharField(source="email")
    code_postal = serializers.CharField(source="post_code")
    code_insee = serializers.CharField(default="")
    commune = serializers.CharField(source="city")
    adresse = serializers.CharField(source="address_line_1")
    complement_adresse = serializers.CharField(source="address_line_2")
    longitude = serializers.FloatField()
    latitude = serializers.FloatField()
    date_maj = serializers.SerializerMethodField()
    antenne = serializers.SerializerMethodField()
    lien_source = serializers.SerializerMethodField()
    horaires_ouverture = serializers.CharField(default="")
    accessibilite = serializers.CharField(default="")
    labels_nationaux = serializers.ListSerializer(child=serializers.CharField(), default=[])
    labels_autres = serializers.ListSerializer(child=serializers.CharField(), default=[])
    thematiques = serializers.ListSerializer(child=serializers.CharField(), default=[])

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
            "antenne",
            "lien_source",
            "horaires_ouverture",
            "accessibilite",
            "labels_nationaux",
            "labels_autres",
            "thematiques",
        ]
        read_only_fields = fields

    def get_siret(self, obj) -> str:
        if obj.source == Siae.SOURCE_USER_CREATED:
            if re.search(r"999\d\d$", obj.siret) is None:
                # Though this siae may refer to another siae with its asp_id, it owns a proper siret,
                # which makes it a structure in its own right according to data.inclusion
                return obj.siret

            # The `999\d\d` pattern should not be published. There might be a valid siret available
            # for this asp_id on another siae : use the oldest.
            a_parent_siae = (
                Siae.objects.exclude(source=Siae.SOURCE_USER_CREATED)
                .filter(convention__asp_id=obj.asp_id)
                .order_by("created_at", "pk")
                .first()
            )
            if a_parent_siae is not None:
                return a_parent_siae.siret

            # default to siren
            return obj.siret[:9]

        # If the siae source is other than SOURCE_USER_CREATED,
        # then its siret **should** be valid.
        return obj.siret

    def get_presentation_resume(self, obj) -> str:
        return text.Truncator(obj.description).chars(280)

    def get_presentation_detail(self, obj) -> str:
        if len(obj.description) < 280:
            return ""
        return obj.description

    def get_antenne(self, obj) -> bool:
        if obj.source == Siae.SOURCE_USER_CREATED and re.search(r"999\d\d$", obj.siret) is not None:
            return True

        return obj.same_siret_count >= 2

    def get_date_maj(self, obj) -> str:
        dt = obj.updated_at or obj.created_at
        return dt.astimezone(timezone.get_current_timezone()).isoformat()

    def get_lien_source(self, obj) -> str:
        return self.context["request"].build_absolute_uri(obj.get_card_url())


class PrescriberOrgStructureSerializer(serializers.ModelSerializer):
    """Serialize Prescriber Organization instance to the data.inclusion structure schema.

    Fields are based on https://github.com/betagouv/data-inclusion-schema.
    """

    id = serializers.UUIDField(source="uid")
    typologie = serializers.ChoiceField(source="kind", choices=PrescriberOrganizationKind.choices)
    nom = serializers.CharField(source="name")
    rna = serializers.CharField(default="")
    presentation_resume = serializers.SerializerMethodField()
    presentation_detail = serializers.SerializerMethodField()
    site_web = serializers.CharField(source="website")
    telephone = serializers.CharField(source="phone")
    courriel = serializers.CharField(source="email")
    code_postal = serializers.CharField(source="post_code")
    code_insee = serializers.CharField(default="")
    commune = serializers.CharField(source="city")
    adresse = serializers.CharField(source="address_line_1")
    complement_adresse = serializers.CharField(source="address_line_2")
    longitude = serializers.FloatField()
    latitude = serializers.FloatField()
    source = serializers.CharField(default="")
    date_maj = serializers.SerializerMethodField()
    antenne = serializers.BooleanField(default=False)
    lien_source = serializers.SerializerMethodField()
    horaires_ouverture = serializers.CharField(default="")
    accessibilite = serializers.CharField(default="")
    labels_nationaux = serializers.ListSerializer(child=serializers.CharField(), default=[])
    labels_autres = serializers.ListSerializer(child=serializers.CharField(), default=[])
    thematiques = serializers.ListSerializer(child=serializers.CharField(), default=[])

    class Meta:
        model = PrescriberOrganization
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
            "antenne",
            "lien_source",
            "horaires_ouverture",
            "accessibilite",
            "labels_nationaux",
            "labels_autres",
            "thematiques",
        ]
        read_only_fields = fields

    def get_presentation_resume(self, obj) -> str:
        return text.Truncator(obj.description).chars(280)

    def get_presentation_detail(self, obj) -> str:
        if len(obj.description) < 280:
            return ""
        return obj.description

    def get_date_maj(self, obj) -> str:
        dt = obj.updated_at or obj.created_at
        return dt.astimezone(timezone.get_current_timezone()).isoformat()

    def get_lien_source(self, obj) -> str:
        url = obj.get_card_url()
        return self.context["request"].build_absolute_uri(url) if url else None
