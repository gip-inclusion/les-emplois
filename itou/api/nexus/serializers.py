from rest_framework import serializers

from itou.nexus.enums import STRUCTURE_KIND_MAPPING, USER_KIND_MAPPING, Auth, Role


class MembershipSerializer(serializers.Serializer):
    structure_id = serializers.CharField()
    role = serializers.ChoiceField(choices=Role.choices)


class UserSerializer(serializers.Serializer):
    id = serializers.CharField(source="source_id")
    kind = serializers.CharField(source="source_kind", allow_blank=True)
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.CharField()
    phone = serializers.CharField(allow_blank=True)
    last_login = serializers.DateTimeField(required=False, allow_null=True)
    auth = serializers.ChoiceField(choices=Auth.choices)

    memberships = MembershipSerializer(many=True)

    def validate_kind(self, value):
        if value not in USER_KIND_MAPPING[self.context["source"]]:
            raise serializers.ValidationError(f"«\xa0{value}\xa0» n'est pas un choix valide.")
        return value


class StructureSerializer(serializers.Serializer):
    id = serializers.CharField(source="source_id")
    kind = serializers.CharField(source="source_kind", allow_blank=True)
    siret = serializers.CharField()
    name = serializers.CharField()
    phone = serializers.CharField(allow_blank=True)
    email = serializers.CharField(allow_blank=True)
    address_line_1 = serializers.CharField(allow_blank=True)
    address_line_2 = serializers.CharField(allow_blank=True)
    post_code = serializers.CharField()
    city = serializers.CharField()
    department = serializers.CharField()

    website = serializers.URLField(allow_blank=True)
    opening_hours = serializers.CharField(allow_blank=True)
    accessibility = serializers.URLField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    source_link = serializers.URLField(allow_blank=True)

    def validate_kind(self, value):
        if value not in STRUCTURE_KIND_MAPPING[self.context["source"]]:
            raise serializers.ValidationError(f"«\xa0{value}\xa0» n'est pas un choix valide.")
        return value


class DeleteObjectSerializer(serializers.Serializer):
    id = serializers.CharField(source="source_id")


class SyncCompletedSerializer(serializers.Serializer):
    started_at = serializers.DateTimeField()
