import re

from django.utils import timezone
from rest_framework import serializers

from itou.companies.enums import CompanyKind, CompanySource
from itou.companies.models import Company
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization


class BaseStructureSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="uid")
    nom = serializers.CharField(source="display_name")
    description = serializers.CharField()
    site_web = serializers.CharField(source="website")
    siret = serializers.CharField()
    telephone = serializers.CharField(source="phone")
    courriel = serializers.CharField(source="email")
    code_postal = serializers.CharField(source="post_code")
    commune = serializers.CharField(source="city")
    adresse = serializers.CharField(source="address_line_1")
    complement_adresse = serializers.CharField(source="address_line_2")
    longitude = serializers.FloatField()
    latitude = serializers.FloatField()
    date_maj = serializers.SerializerMethodField()
    lien_source = serializers.SerializerMethodField()

    class Meta:
        fields = [
            "id",
            "nom",
            "siret",
            "description",
            "site_web",
            "telephone",
            "courriel",
            "code_postal",
            "commune",
            "adresse",
            "complement_adresse",
            "longitude",
            "latitude",
            "date_maj",
            "lien_source",
            "kind",
        ]
        read_only_fields = fields

    def get_date_maj(self, obj) -> str:
        dt = obj.updated_at or obj.created_at
        return dt.astimezone(timezone.get_current_timezone()).isoformat()

    def get_lien_source(self, obj) -> str:
        card_url = obj.get_card_url()
        if card_url:
            return self.context["request"].build_absolute_uri(card_url)
        return None


class CompanySerializer(BaseStructureSerializer):
    siret = serializers.SerializerMethodField()
    kind = serializers.ChoiceField(choices=CompanyKind.choices)

    class Meta(BaseStructureSerializer.Meta):
        model = Company

    def get_siret(self, obj) -> str:
        if obj.source == CompanySource.USER_CREATED:
            if re.search(r"999\d\d$", obj.siret) is None:
                # Though this siae may refer to another siae with its asp_id, it owns a proper siret,
                # which makes it a structure in its own right according to data.inclusion
                return obj.siret

            # The `999\d\d` pattern should not be published. There might be a valid siret available
            # for this asp_id on another siae : use the oldest.
            a_parent_siae = (
                Company.objects.exclude(source=CompanySource.USER_CREATED)
                .filter(convention_id=obj.convention_id, siret__startswith=obj.siren)
                .order_by("created_at", "pk")
                .first()
            )
            if a_parent_siae is not None:
                return a_parent_siae.siret

            return None

        # If the siae source is other than CompanySource.USER_CREATED,
        # then its siret **should** be valid.
        return obj.siret


class PrescriberOrgStructureSerializer(BaseStructureSerializer):
    kind = serializers.ChoiceField(choices=PrescriberOrganizationKind.choices)

    class Meta(BaseStructureSerializer.Meta):
        model = PrescriberOrganization
