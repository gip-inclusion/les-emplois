from functools import partial

import pytest
from django.urls import reverse

from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.testing import parse_response_to_soup
from tests.www.recommendations.conftest import OTHER_SAFIR, SAFIR


TAB_TEXT = "Actions recommandées"
NAV_SELECTOR = "#offcanvasNav > .offcanvas-body > nav"


@pytest.mark.parametrize(
    "factory,visible",
    [
        (
            partial(
                PrescriberFactory,
                membership__organization__france_travail=True,
                membership__organization__code_safir_pole_emploi=SAFIR,
            ),
            True,
        ),
        (
            partial(
                PrescriberFactory,
                membership__organization__france_travail=True,
                membership__organization__code_safir_pole_emploi=OTHER_SAFIR,
            ),
            False,
        ),
        (partial(EmployerFactory, membership=True), False),
        (JobSeekerFactory, False),
    ],
    ids=["authorized_advisor", "unauthorized_advisor", "employer", "job_seeker"],
)
def test_nav_visibility(client, factory, visible):
    client.force_login(factory())
    response = client.get(reverse("dashboard:index"), follow=True)
    assert (
        "Actions recommandées" in parse_response_to_soup(response, "#offcanvasNav > .offcanvas-body > nav").get_text()
    ) is visible
