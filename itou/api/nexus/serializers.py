from rest_framework import serializers

from itou.nexus.enums import STRUCTURE_KIND_MAPPING, USER_KIND_MAPPING
from itou.nexus.models import NexusMembership, NexusStructure, NexusUser


class MembershipSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="source_id")
    user_id = serializers.CharField()
    structure_id = serializers.CharField()

    class Meta:
        model = NexusMembership
        fields = (
            "id",
            "user_id",
            "structure_id",
            "role",
        )


class UserSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="source_id")
    kind = serializers.CharField(source="source_kind", allow_blank=True)

    class Meta:
        model = NexusUser
        fields = (
            "id",
            "kind",
            "first_name",
            "last_name",
            "email",
            "phone",
            "last_login",
            "auth",
        )

    def validate_kind(self, value):
        if value not in USER_KIND_MAPPING[self.context["source"]]:
            raise serializers.ValidationError(f"«\xa0{value}\xa0» n'est pas un choix valide.")
        return value


class StructureSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="source_id")
    kind = serializers.CharField(source="source_kind", allow_blank=True)

    class Meta:
        model = NexusStructure

        fields = (
            "id",
            "kind",
            "siret",
            "name",
            "phone",
            "email",
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "department",
            "website",
            "opening_hours",
            "accessibility",
            "description",
            "source_link",
        )

    def validate_kind(self, value):
        if value not in STRUCTURE_KIND_MAPPING[self.context["source"]]:
            raise serializers.ValidationError(f"«\xa0{value}\xa0» n'est pas un choix valide.")
        return value


class DeleteObjectSerializer(serializers.Serializer):
    id = serializers.CharField(source="source_id")


class SyncCompletedSerializer(serializers.Serializer):
    started_at = serializers.DateTimeField()
