from rest_framework import serializers

from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation


class OrientationSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField()
    status = serializers.CharField()
    beneficiary_name = serializers.CharField(source="beneficiary.get_full_name")
    france_travail_id = serializers.SerializerMethodField()
    service_uid = serializers.CharField(source="service.uid")
    sender_organization_name = serializers.CharField(source="sender_organization.display_name")
    sender_name = serializers.CharField(source="sender.get_full_name")
    process_link = serializers.URLField(source="new_process_link")

    class Meta:
        model = Orientation
        fields = (
            "created_at",
            "status",
            "beneficiary_name",
            "france_travail_id",
            "service_uid",
            "sender_organization_name",
            "sender_name",
            "process_link",
        )
        read_only_fields = fields

    def get_france_travail_id(self, obj) -> str | None:
        if obj.status == OrientationStatus.ACCEPTED:
            return obj.beneficiary.jobseeker_profile.pole_emploi_id
        return None


class OrientationRequestSerializer(serializers.Serializer):
    structure_uid = serializers.CharField(
        write_only=True, label="Identifiant data·inclusion de la structure qui reçoit les demandes d’orientations"
    )


class OrientationCountSerializer(serializers.Serializer):
    pending_count = serializers.IntegerField()
    total_count = serializers.IntegerField(read_only=True)
