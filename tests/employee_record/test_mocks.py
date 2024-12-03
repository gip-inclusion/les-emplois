from textwrap import dedent

from itou.companies.enums import CompanyKind
from itou.employee_record.enums import Status
from itou.employee_record.mocks import asp_test_siaes, fake_serializers
from itou.employee_record.models import EmployeeRecordBatch, EmployeeRecordUpdateNotification
from tests.employee_record.factories import EmployeeRecordWithProfileFactory


def test_get_staging_data(mocker):
    mocker.patch.object(
        asp_test_siaes,
        "STAGING_DATA",
        dedent(
            """
            11111111111111;ONE;AI11111111111
            22222222222222;TWO;EI22222222222;EITI22222222222
            33333333333333;THREE;ACI33333333333;AI33333333333;ETTI33333333333
            """
        ),
    )

    assert asp_test_siaes.get_staging_data() == {
        "ACI": ["33333333333333"],
        "AI": ["11111111111111", "33333333333333"],
        "EI": ["22222222222222"],
        "EITI": ["22222222222222"],
        "ETTI": ["33333333333333"],
    }


def get_staging_siret_from_kind(mocker):
    mocker.patch.object(
        asp_test_siaes,
        "STAGING_DATA",
        dedent(
            """
            11111111111111;ONE;AI11111111111
            22222222222222;TWO;AI22222222222
            """
        ),
    )

    assert asp_test_siaes.get_staging_siret_from_kind(CompanyKind.AI, "00000000000000") == "11111111111111"
    assert asp_test_siaes.get_staging_siret_from_kind(CompanyKind.AI, "00000000000001") == "22222222222222"
    assert asp_test_siaes.get_staging_siret_from_kind(CompanyKind.AI, "00000000000003") == "11111111111111"


def test_fake_serializers():
    employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
    notification = EmployeeRecordUpdateNotification(employee_record=employee_record)

    assert fake_serializers.TestEmployeeRecordBatchSerializer(EmployeeRecordBatch([employee_record])).data
    assert fake_serializers.TestEmployeeRecordUpdateNotificationBatchSerializer(
        EmployeeRecordBatch([notification])
    ).data
