from django.utils import timezone

from itou.analytics import models, users
from tests.users import factories as users_factories


def test_datum_name_value():
    assert models.DatumCode.USER_COUNT.value == "US-101"
    assert models.DatumCode.USER_JOB_SEEKER_COUNT.value == "US-111"
    assert models.DatumCode.USER_PRESCRIBER_COUNT.value == "US-112"
    assert models.DatumCode.USER_EMPLOYER_COUNT.value == "US-113"
    assert models.DatumCode.USER_LABOR_INSPECTOR_COUNT.value == "US-114"
    assert models.DatumCode.USER_ITOU_STAFF_COUNT.value == "US-115"


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
    users_factories.PrescriberFactory.create_batch(3, membership=True)
    users_factories.EmployerFactory.create_batch(4, membership=True)
    users_factories.LaborInspectorFactory.create_batch(5, membership=True)
    users_factories.ItouStaffFactory.create_batch(6)
    users_factories.JobSeekerFactory(is_active=False)
    users_factories.PrescriberFactory()  # no membership we don't count it
    # FIXME: Test with a professionnal with all 3 memberships
    assert users.collect_analytics_data(timezone.now()) == {
        models.DatumCode.USER_COUNT: 20,
        models.DatumCode.USER_JOB_SEEKER_COUNT: 2,
        models.DatumCode.USER_PRESCRIBER_COUNT: 3,
        models.DatumCode.USER_EMPLOYER_COUNT: 4,
        models.DatumCode.USER_LABOR_INSPECTOR_COUNT: 5,
        models.DatumCode.USER_ITOU_STAFF_COUNT: 6,
    }
