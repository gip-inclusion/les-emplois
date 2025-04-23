import itertools

import pytest

from itou.eligibility.enums import CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS, AdministrativeCriteriaKind
from itou.users.enums import UserKind
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory


@pytest.mark.parametrize(
    "criteria,expected",
    [
        *zip(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS, itertools.repeat(True)),
        *zip(
            set(AdministrativeCriteriaKind.common()) - CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS,
            itertools.repeat(False),
        ),
    ],
)
@pytest.mark.parametrize("from_kind", {UserKind.EMPLOYER, UserKind.PRESCRIBER})
@pytest.mark.parametrize("factory", {IAEEligibilityDiagnosisFactory, GEIQEligibilityDiagnosisFactory})
def test_criteria_can_be_certified(factory, from_kind, criteria, expected):
    diagnosis = IAEEligibilityDiagnosisFactory(
        job_seeker__born_in_france=True, criteria_kinds=[criteria], **{f"from_{from_kind}": True}
    )
    assert diagnosis.criteria_can_be_certified() == expected
