from itou.employee_record.mocks.asp_test_siaes import get_staging_siret_from_kind
from itou.employee_record.models import EmployeeRecord, EmployeeRecordUpdateNotification
from itou.employee_record.serializers import (
    EmployeeRecordBatchSerializer,
    EmployeeRecordSerializer,
    EmployeeRecordUpdateNotificationSerializer,
)


class TestEmployeeRecordSerializer(EmployeeRecordSerializer):
    def to_representation(self, instance: EmployeeRecord):
        """
        Test version of the employee record serializer

        Align data with the ASP's "validation" platform as only a limited
        predefined set of SIAE/SIRET/Financial annex number is possible.
        """

        result = super().to_representation(instance)
        # Map test fields / values
        result["siret"] = get_staging_siret_from_kind(instance.job_application.to_company.kind, instance.siret)

        return result


class TestEmployeeRecordBatchSerializer(EmployeeRecordBatchSerializer):
    # Overrides
    lignesTelechargement = TestEmployeeRecordSerializer(many=True, source="elements")


class TestEmployeeRecordUpdateNotificationSerializer(EmployeeRecordUpdateNotificationSerializer):
    def to_representation(self, instance: EmployeeRecordUpdateNotification):
        """
        Test version of the employee record notification serializer

        Align data with the ASP's "validation" platform as only a limited
        predefined set of SIAE/SIRET/Financial annex number is possible.
        """

        result = super().to_representation(instance)

        # Map test fields / values
        result["siret"] = get_staging_siret_from_kind(
            instance.employee_record.job_application.to_company.kind, instance.employee_record.siret
        )

        return result


class TestEmployeeRecordUpdateNotificationBatchSerializer(EmployeeRecordBatchSerializer):
    # Overrides
    lignesTelechargement = TestEmployeeRecordUpdateNotificationSerializer(many=True, source="elements")
