from rest_framework import serializers

from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation


class OrientationSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField()
    status = serializers.CharField()
    beneficiary = serializers.CharField(source="beneficiary.get_full_name")
    pole_emploi_id = serializers.SerializerMethodField()
    service = serializers.CharField(source="service.uid")
    sender_organization = serializers.CharField(source="sender_organization.display_name")
    sender = serializers.CharField(source="sender.get_full_name")
    process_link = serializers.URLField(source="new_process_link")

    class Meta:
        model = Orientation
        fields = (
            "created_at",
            "status",
            "beneficiary",
            "pole_emploi_id",
            "service",
            "sender_organization",
            "sender",
            "process_link",
        )
        read_only_fields = fields

    def get_pole_emploi_id(self, obj) -> str | None:
        if obj.status == OrientationStatus.ACCEPTED:
            return obj.beneficiary.jobseeker_profile.pole_emploi_id
        return None


class OrientationRequestSerializer(serializers.Serializer):
    structure_uid = serializers.CharField(
        write_only=True, label="Identifiant data·inclusion de la structure qui reçoit les demandes d’orientations"
    )
