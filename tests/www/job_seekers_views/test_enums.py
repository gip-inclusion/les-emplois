import pytest

from itou.www.job_seekers_views.enums import JobSeekerOrder


@pytest.mark.parametrize("order", JobSeekerOrder)
@pytest.mark.no_django_db
def test_opposite(order):
    assert order.opposite != order
    assert order.opposite.opposite == order
