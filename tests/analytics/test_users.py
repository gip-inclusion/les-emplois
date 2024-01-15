from django.utils import timezone

from itou.analytics import models, users
from tests.users import factories as users_factories


def test_datum_name_value():
    assert models.DatumCode.USER_COUNT.value == "US-001"
    assert models.DatumCode.USER_JOB_SEEKER_COUNT.value == "US-011"
    assert models.DatumCode.USER_PRESCRIBER_COUNT.value == "US-012"
    assert models.DatumCode.USER_EMPLOYER_COUNT.value == "US-013"
    assert models.DatumCode.USER_LABOR_INSPECTOR_COUNT.value == "US-014"
    assert models.DatumCode.USER_ITOU_STAFF_COUNT.value == "US-015"


def test_collect_analytics_data_return_all_codes():
    assert users.collect_analytics_data(timezone.now()).keys() == {
        models.DatumCode.USER_COUNT,
        models.DatumCode.USER_JOB_SEEKER_COUNT,
        models.DatumCode.USER_PRESCRIBER_COUNT,
        models.DatumCode.USER_EMPLOYER_COUNT,
        models.DatumCode.USER_LABOR_INSPECTOR_COUNT,
        models.DatumCode.USER_ITOU_STAFF_COUNT,
    }


def test_collect_analytics_when_no_user_exists():
    assert users.collect_analytics_data(timezone.now()) == {
        models.DatumCode.USER_COUNT: 0,
        models.DatumCode.USER_JOB_SEEKER_COUNT: 0,
        models.DatumCode.USER_PRESCRIBER_COUNT: 0,
        models.DatumCode.USER_EMPLOYER_COUNT: 0,
        models.DatumCode.USER_LABOR_INSPECTOR_COUNT: 0,
        models.DatumCode.USER_ITOU_STAFF_COUNT: 0,
    }


def test_collect_analytics_with_data():
    users_factories.JobSeekerFactory.create_batch(2)
    users_factories.PrescriberFactory.create_batch(3)
    users_factories.EmployerFactory.create_batch(4)
    users_factories.LaborInspectorFactory.create_batch(5)
    users_factories.ItouStaffFactory.create_batch(6)
    assert users.collect_analytics_data(timezone.now()) == {
        models.DatumCode.USER_COUNT: 20,
        models.DatumCode.USER_JOB_SEEKER_COUNT: 2,
        models.DatumCode.USER_PRESCRIBER_COUNT: 3,
        models.DatumCode.USER_EMPLOYER_COUNT: 4,
        models.DatumCode.USER_LABOR_INSPECTOR_COUNT: 5,
        models.DatumCode.USER_ITOU_STAFF_COUNT: 6,
    }
