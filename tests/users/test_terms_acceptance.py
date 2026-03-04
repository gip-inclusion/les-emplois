import pytest
from django.utils import timezone

from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


@pytest.mark.parametrize("accepted", [True, False])
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
def test_must_accept_terms(factory, accepted):
    user = factory(terms_accepted_at=timezone.now() if accepted else None)
    is_concerned_by_terms = factory in (PrescriberFactory, EmployerFactory, LaborInspectorFactory)
    assert user.must_accept_terms() is (is_concerned_by_terms and not accepted)
