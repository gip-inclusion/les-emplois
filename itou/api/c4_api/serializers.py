import re

from rest_framework import serializers

from itou.companies.enums import CompanyKind
from itou.companies.models import Company


class C4CompanySerializer(serializers.ModelSerializer):
    """Serialize Company instance for the c4 project

    Fields are based on https://github.com/betagouv/itou-marche/blob/e3baa3486254ec54036f9de8f46ed6fcf267ca8f/lemarche/siaes/management/commands/sync_c1_c4.py
    """

    id = serializers.IntegerField()
    siret = serializers.SerializerMethodField()
    naf = serializers.CharField()
    kind = serializers.ChoiceField(choices=CompanyKind.choices)
    name = serializers.CharField()
    brand = serializers.CharField()
    phone = serializers.CharField()
    email = serializers.CharField()
    website = serializers.CharField()
    description = serializers.CharField()
    address_line_1 = serializers.CharField()
    address_line_2 = serializers.CharField()
    post_code = serializers.CharField()
    city = serializers.CharField()
    department = serializers.CharField()
    source = serializers.ChoiceField(choices=Company.SOURCE_CHOICES)
    longitude = serializers.FloatField()
    latitude = serializers.FloatField()
    convention_is_active = serializers.BooleanField(source="convention.is_active", allow_null=True)
    convention_asp_id = serializers.IntegerField(source="convention.asp_id", allow_null=True)
    admin_name = serializers.SerializerMethodField(allow_null=True)
    admin_email = serializers.SerializerMethodField(allow_null=True)

    class Meta:
        model = Company
        fields = [
            "id",
            "siret",
            "naf",
            "kind",
            "name",
            "brand",
            "phone",
            "email",
            "website",
            "description",
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "department",
            "source",
            "latitude",
            "longitude",
            "convention_is_active",
            "convention_asp_id",
            "admin_name",
            "admin_email",
        ]
        read_only_fields = fields

    def get_siret(self, obj) -> str:
        if obj.source == Company.SOURCE_USER_CREATED:
            if re.search(r"999\d\d$", obj.siret) is None:
                # Though this siae may refer to another siae with its asp_id, it owns a proper siret,
                # which makes it a structure in its own right according to data.inclusion
                return obj.siret

            # The `999\d\d` pattern should not be published. There might be a valid siret available
            # for this asp_id on another siae : use the oldest.
            a_parent_siae = (
                Company.objects.exclude(source=Company.SOURCE_USER_CREATED)
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

    def get_admin_name(self, obj) -> str | None:
        if obj.admin:
            return obj.admin[0].user.get_full_name()
        return None

    def get_admin_email(self, obj) -> str | None:
        if obj.admin:
            return obj.admin[0].user.email
        return None
