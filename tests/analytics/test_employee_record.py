import itertools

import pytest
from django.utils import timezone

from itou.analytics import employee_record, models
from tests.employee_record import factories as employee_record_factories


def test_datum_name_value():
    assert models.DatumCode.EMPLOYEE_RECORD_COUNT.value == "ER-001"
    assert models.DatumCode.EMPLOYEE_RECORD_DELETED.value == "ER-002"

    assert models.DatumCode.EMPLOYEE_RECORD_PROCESSED_AT_FIRST_EXCHANGE.value == "ER-101"
    assert models.DatumCode.EMPLOYEE_RECORD_WITH_ERROR_AT_FIRST_EXCHANGE.value == "ER-102"
    assert models.DatumCode.EMPLOYEE_RECORD_WITH_ERROR_3436_AT_FIRST_EXCHANGE.value == "ER-102-3436"
    assert models.DatumCode.EMPLOYEE_RECORD_WITH_AT_LEAST_ONE_ERROR.value == "ER-103"


def test_collect_analytics_data_return_all_codes():
    assert employee_record.collect_analytics_data(timezone.now()).keys() == {
        models.DatumCode.EMPLOYEE_RECORD_COUNT,
        models.DatumCode.EMPLOYEE_RECORD_DELETED,
        models.DatumCode.EMPLOYEE_RECORD_PROCESSED_AT_FIRST_EXCHANGE,
        models.DatumCode.EMPLOYEE_RECORD_WITH_ERROR_AT_FIRST_EXCHANGE,
        models.DatumCode.EMPLOYEE_RECORD_WITH_ERROR_3436_AT_FIRST_EXCHANGE,
        models.DatumCode.EMPLOYEE_RECORD_WITH_AT_LEAST_ONE_ERROR,
    }


def test_collect_analytics_when_employee_records_does_not_exists():
    assert employee_record.collect_analytics_data(timezone.now()) == {
        models.DatumCode.EMPLOYEE_RECORD_COUNT: 0,
        models.DatumCode.EMPLOYEE_RECORD_DELETED: 0,
        models.DatumCode.EMPLOYEE_RECORD_PROCESSED_AT_FIRST_EXCHANGE: 0,
        models.DatumCode.EMPLOYEE_RECORD_WITH_ERROR_AT_FIRST_EXCHANGE: 0,
        models.DatumCode.EMPLOYEE_RECORD_WITH_ERROR_3436_AT_FIRST_EXCHANGE: 0,
        models.DatumCode.EMPLOYEE_RECORD_WITH_AT_LEAST_ONE_ERROR: 0,
    }


def test_collect_employee_records_count_when_employee_records_exists():
    employee_record_factories.BareEmployeeRecordFactory.create_batch(3)
    assert employee_record.collect_employee_records_count(timezone.now()) == {
        models.DatumCode.EMPLOYEE_RECORD_COUNT: 3
    }


def test_collect_probably_deleted_employee_records_when_employee_records_exists():
    employee_record_factories.BareEmployeeRecordFactory.create_batch(3)
    assert employee_record.collect_probably_deleted_employee_records(timezone.now()) == {
        models.DatumCode.EMPLOYEE_RECORD_DELETED: 0
    }


@pytest.mark.parametrize(
    "slicer,expected",
    [
        (slice(0, 1), 0),
        (slice(1, 2), 1),
        (slice(2, 3), 1),
        (slice(3, 4), 1),
        (slice(4, 5), 0),
        (slice(1, 3), 2),
        (slice(1, 4, 2), 2),
    ],
    ids=str,
)
def test_collect_probably_deleted_employee_records_when_some_employee_records_were_deleted(slicer, expected):
    employee_records = employee_record_factories.BareEmployeeRecordFactory.create_batch(5)
    for obj in employee_records[slicer]:
        obj.delete()

    assert employee_record.collect_probably_deleted_employee_records(timezone.now()) == {
        models.DatumCode.EMPLOYEE_RECORD_DELETED: expected,
    }


def test_collect_employee_records_processing_code_on_first_exchange_when_employee_records_exists():
    employee_record_factories.BareEmployeeRecordFactory.create_batch(3, asp_processing_code="0000")
    employee_record_factories.BareEmployeeRecordFactory.create_batch(3, asp_processing_code="3436")
    employee_record_factories.BareEmployeeRecordFactory.create_batch(3, asp_processing_code="9999")

    assert employee_record.collect_employee_records_processing_code_of_first_exchange(timezone.now()) == {
        models.DatumCode.EMPLOYEE_RECORD_PROCESSED_AT_FIRST_EXCHANGE: 3,
        models.DatumCode.EMPLOYEE_RECORD_WITH_ERROR_AT_FIRST_EXCHANGE: 6,
        models.DatumCode.EMPLOYEE_RECORD_WITH_ERROR_3436_AT_FIRST_EXCHANGE: 3,
    }


def test_collect_employee_record_with_at_least_one_error():
    for er_code, ern_code in itertools.product(["0000", "9999"], repeat=2):
        employee_record_factories.BareEmployeeRecordUpdateNotificationFactory.create_batch(
            3,
            status=employee_record_factories.NotificationStatus.SENT,
            asp_processing_code=ern_code,
            employee_record=employee_record_factories.BareEmployeeRecordFactory(asp_processing_code=er_code),
        )

    assert employee_record.collect_employee_record_with_at_least_one_error(timezone.now()) == {
        models.DatumCode.EMPLOYEE_RECORD_WITH_AT_LEAST_ONE_ERROR: 3,
    }
