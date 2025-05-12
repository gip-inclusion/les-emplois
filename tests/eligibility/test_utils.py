import datetime

import pytest
from django.utils import timezone

from itou.eligibility.enums import CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS, AdministrativeCriteriaAnnex
from itou.eligibility.models import GEIQAdministrativeCriteria, GEIQSelectedAdministrativeCriteria
from itou.eligibility.utils import geiq_criteria_for_display, iae_criteria_for_display
from itou.utils.types import InclusiveDateRange
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory


@pytest.mark.parametrize(
    "factory,method",
    [
        pytest.param(GEIQEligibilityDiagnosisFactory, geiq_criteria_for_display, id="geiq"),
        pytest.param(IAEEligibilityDiagnosisFactory, iae_criteria_for_display, id="iae"),
    ],
)
def test_criteria_for_display(factory, method):
    def _assert_considered_certified(diagnosis, expected, hiring_start_at):
        [criterion] = method(diagnosis, hiring_start_at=hiring_start_at)
        assert criterion.is_considered_certified is expected

    def assert_considered_certified(diagnosis, hiring_start_at=None):
        _assert_considered_certified(diagnosis, True, hiring_start_at=hiring_start_at)

    def assert_not_considered_certified(diagnosis, hiring_start_at=None):
        _assert_considered_certified(diagnosis, False, hiring_start_at=hiring_start_at)

    diagnosis = factory(
        certifiable=True,
        criteria_kinds=list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS)[:1],
    )
    if factory is GEIQEligibilityDiagnosisFactory:
        # Ignored because they are not displayed.
        ignored_crit = (
            GEIQAdministrativeCriteria.objects.filter(annex=AdministrativeCriteriaAnnex.NO_ANNEX).order_by("?").first()
        )
        GEIQSelectedAdministrativeCriteria(administrative_criteria=ignored_crit, eligibility_diagnosis=diagnosis)

    [selected_criterion] = diagnosis.selected_administrative_criteria.all()
    selected_criterion.certified = True
    today = timezone.localdate()
    start = today - datetime.timedelta(days=10)
    end = today + datetime.timedelta(days=10)
    selected_criterion.certification_period = InclusiveDateRange(start, end)
    selected_criterion.save(update_fields=["certification_period", "certified"])
    assert_not_considered_certified(diagnosis)
    assert_not_considered_certified(diagnosis, hiring_start_at=start - datetime.timedelta(days=1))
    assert_considered_certified(diagnosis, hiring_start_at=start)
    assert_considered_certified(diagnosis, hiring_start_at=today)
    assert_considered_certified(diagnosis, hiring_start_at=end)
    assert_considered_certified(diagnosis, hiring_start_at=end + datetime.timedelta(days=1))
    end_limit = end + datetime.timedelta(days=selected_criterion.CERTIFICATION_GRACE_PERIOD_DAYS)
    assert_considered_certified(diagnosis, hiring_start_at=end_limit)
    assert_not_considered_certified(diagnosis, hiring_start_at=end_limit + datetime.timedelta(days=1))
