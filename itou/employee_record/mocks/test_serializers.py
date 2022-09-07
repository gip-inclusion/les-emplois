from itou.employee_record.mocks.asp_test_siaes import asp_to_siret_from_fixtures
from itou.employee_record.serializers import (
    EmployeeRecordBatchSerializer,
    EmployeeRecordSerializer,
    EmployeeRecordUpdateNotificationSerializer,
)


class TestEmployeeRecordSerializer(EmployeeRecordSerializer):
    def to_representation(self, instance):
        """
        Test version of the employee record serializer
        Basically uses the ASP_ID -> SIRET mapping to be aligned with ASP test platform
        (only a limited predefined set of SIAE/SIRET/Financial annex number is possible)
        """

        result = super().to_representation(instance)

        # Map test fields / values

        test_data = asp_to_siret_from_fixtures(instance.asp_id)

        result["mesure"] = test_data["mesure"]
        result["siret"] = test_data["siret"]

        return result


class TestEmployeeRecordBatchSerializer(EmployeeRecordBatchSerializer):
    # Overrides
    lignesTelechargement = TestEmployeeRecordSerializer(many=True, source="elements")


class TestEmployeeRecordUpdateNotificationSerializer(EmployeeRecordUpdateNotificationSerializer):
    def to_representation(self, instance):
        """
        Test version of the employee record serializer
        Basically uses the ASP_ID -> SIRET mapping to be aligned with ASP test platform
        (only a limited predefined set of SIAE/SIRET/Financial annex number is possible)
        """

        result = super().to_representation(instance)

        # Map test fields / values

        test_data = asp_to_siret_from_fixtures(instance.employee_record.asp_id)

        result["mesure"] = test_data["mesure"]
        result["siret"] = test_data["siret"]

        return result


class TestEmployeeRecordUpdateNotificationBatchSerializer(EmployeeRecordBatchSerializer):
    # Overrides
    lignesTelechargement = TestEmployeeRecordUpdateNotificationSerializer(many=True, source="elements")
