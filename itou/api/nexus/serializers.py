from rest_framework import exceptions, serializers

from itou.nexus.enums import USER_KIND_MAPPING, Auth, NexusStructureKind, Role


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
    last_login = serializers.DateTimeField()
    auth = serializers.ChoiceField(choices=Auth.choices)

    memberships = MembershipSerializer(many=True)

    def __init__(self, source, **kwargs):
        super().__init__(**kwargs)
        self.source = source

    def validate_kind(self, value):
        if value not in USER_KIND_MAPPING[self.source]:
            raise serializers.ValidationError(f"{value} n'est pas un choix valide.")
        return value


class StructureSerializer(serializers.Serializer):
    id = serializers.CharField(source="source_id")
    kind = serializers.ChoiceField(source="source_kind", choices=NexusStructureKind.choices)
    siret = serializers.CharField()
    name = serializers.CharField()
    phone = serializers.CharField(allow_blank=True)
    email = serializers.CharField()
    address_line_1 = serializers.CharField()
    address_line_2 = serializers.CharField(allow_blank=True)
    post_code = serializers.CharField()
    city = serializers.CharField()
    department = serializers.CharField()

    website = serializers.URLField(allow_blank=True)
    opening_hours = serializers.CharField(allow_blank=True)
    accessibility = serializers.URLField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    source_link = serializers.URLField(allow_blank=True)


class DeleteObjectSerializer(serializers.Serializer):
    id = serializers.CharField(source="source_id")


class SyncSerializer(serializers.Serializer):
    start = serializers.BooleanField(required=False)
    started_at = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        validated_data = super().validate(attrs)
        if len(validated_data) == 0:
            raise exceptions.ValidationError("Missing 'start' or 'started_at'")
        if len(validated_data) == 2:
            raise exceptions.ValidationError("Only one of 'start' or 'started_at' is allowed")

        return validated_data
