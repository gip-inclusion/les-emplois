import datetime
from collections import Counter

from itou.eligibility.enums import (
    ADMINISTRATIVE_CRITERIA_LEVEL_2_REQUIRED_FOR_SIAE_KIND,
    AdministrativeCriteriaAnnex,
    AdministrativeCriteriaLevel,
)
from itou.utils.types import InclusiveDateRange


def iae_has_required_criteria(criteria, company_kind):
    level_2_count = 0
    for criterion in criteria:
        if criterion.level == AdministrativeCriteriaLevel.LEVEL_1:
            return True
        level_2_count += 1
    return level_2_count >= ADMINISTRATIVE_CRITERIA_LEVEL_2_REQUIRED_FOR_SIAE_KIND[company_kind]


def _inclusive_overlap(date_range1: InclusiveDateRange, date_range2: InclusiveDateRange):
    return date_range1.lower <= date_range2.upper and date_range2.lower <= date_range1.upper


def _criteria_for_display(selected_criteria, hiring_start_at):
    for criterion in selected_criteria:
        criterion.is_considered_certified = False
        if hiring_start_at and criterion.certified:
            validity_period = InclusiveDateRange(
                hiring_start_at - datetime.timedelta(days=criterion.CERTIFICATION_GRACE_PERIOD_DAYS),
                hiring_start_at,
            )
            criterion.is_considered_certified = _inclusive_overlap(validity_period, criterion.certification_period)
    return selected_criteria


def iae_criteria_for_display(eligibility_diagnosis, hiring_start_at=None):
    return _criteria_for_display(eligibility_diagnosis.selected_administrative_criteria.all(), hiring_start_at)


def geiq_criteria_for_display(eligibility_diagnosis, hiring_start_at=None):
    return _criteria_for_display(
        eligibility_diagnosis.selected_administrative_criteria.exclude(
            administrative_criteria__annex=AdministrativeCriteriaAnnex.NO_ANNEX
        ),
        hiring_start_at,
    )


def geiq_allowance_amount(is_authorized_prescriber, administrative_criteria) -> int:
    """Amount of granted allowance for job seeker.

    Calculated in function of:
        - author kind
        - number, annex and level of administrative criteria.
    Currently, only 3 amounts possible:
        - 0
        - 814EUR
        - 1400EUR
    """

    # Even when no criteria in the diagnosis
    if is_authorized_prescriber:
        return 1400

    # Count by annex
    annex_cnt = Counter(c.annex for c in administrative_criteria)

    # Only annex 2 administrative criteria have a level defined
    level_cnt = Counter(c.level for c in administrative_criteria if c.level)

    # At least one level 1 criterion or at least two level 2 criteria
    if level_cnt["1"] > 0 or level_cnt["2"] > 1:
        return 1400

    # Criteria in both annex ("1+2") must be counted as annex 1
    if annex_cnt["1"] + annex_cnt["1+2"] > 0:
        return 814

    return 0
