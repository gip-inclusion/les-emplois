import decimal

import pytest

from itou.www.geiq_assessments_views.templatetags.geiq_assessments_badges import grant_percentage_badge
from tests.geiq_assessments.factories import AssessmentFactory


@pytest.mark.parametrize(
    "convention_amount,granted_amount,expected",
    [
        (decimal.Decimal(100), decimal.Decimal(100), "100 %"),
        (decimal.Decimal(100), decimal.Decimal(80), "80 %"),
        (decimal.Decimal(100), decimal.Decimal(80.23), "80,2 %"),
        (decimal.Decimal(100_000), decimal.Decimal(80_000.23), "80 %"),
    ],
)
def test_grant_percentage_badge(convention_amount, granted_amount, expected):
    assessment = AssessmentFactory(
        convention_amount=convention_amount,
        granted_amount=granted_amount,
    )
    html = grant_percentage_badge(assessment)
    assert expected in html
