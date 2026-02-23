import datetime

import pytest
from django.utils import timezone

from itou.utils.legal_terms import get_latest_terms_datetime
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


@pytest.mark.parametrize(
    "accepted_at",
    [
        None,  # never
        timezone.now() - datetime.timedelta(days=10 * 365),  # a long time ago
        timezone.now(),  # up to date
    ],
)
@pytest.mark.parametrize(
    "factory",
    [
        ItouStaffFactory,
        PrescriberFactory,
        EmployerFactory,
        LaborInspectorFactory,
        JobSeekerFactory,
    ],
)
def test_must_accept_terms(factory, accepted_at):
    user = factory(terms_accepted_at=accepted_at)
    is_concerned_by_terms = factory in (PrescriberFactory, EmployerFactory, LaborInspectorFactory)
    should_accept = is_concerned_by_terms and (not accepted_at or accepted_at < get_latest_terms_datetime())
    assert user.must_accept_terms is should_accept
