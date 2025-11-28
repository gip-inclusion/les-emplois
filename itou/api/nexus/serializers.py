from rest_framework import serializers


class MembershipSerializer(serializers.Serializer):
    structure_id = serializers.CharField()
    role = serializers.CharField()


class UserSerializer(serializers.Serializer):
    id = serializers.CharField(source="source_id")
    kind = serializers.CharField(source="source_kind", allow_blank=True)
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.CharField()
    phone = serializers.CharField(allow_blank=True)
    last_login = serializers.DateTimeField()
    auth = serializers.CharField()

    memberships = MembershipSerializer(many=True)


class StructureSerializer(serializers.Serializer):
    id = serializers.CharField(source="source_id")
    kind = serializers.CharField(source="source_kind")
    siret = serializers.CharField()
    name = serializers.CharField()
    phone = serializers.CharField(allow_blank=True)
    email = serializers.CharField()


class DeleteObjectSerializer(serializers.Serializer):
    id = serializers.CharField(source="source_id")
