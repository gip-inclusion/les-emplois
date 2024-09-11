from functools import partial

import pytest
from django.urls import reverse

from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.test import parse_response_to_soup


def test_navigation_not_authenticated(snapshot, client):
    response = client.get(reverse("home:hp"), follow=True)
    assert str(parse_response_to_soup(response, "#nav-primary")) == snapshot


@pytest.mark.parametrize(
    "user_factory",
    [
        pytest.param(JobSeekerFactory, id="JobSeeker"),
        pytest.param(
            partial(
                EmployerFactory,
                with_company=True,
                with_company__company__name="ACME Inc.",
            ),
            id="Employer",
        ),
        pytest.param(
            partial(
                LaborInspectorFactory,
                membership=True,
                membership__institution__name="ACME Inc.",
            ),
            id="LaborInspector",
        ),
        pytest.param(PrescriberFactory, id="PrescriberWithoutOrganization"),
        pytest.param(
            partial(
                PrescriberFactory,
                membership__organization__authorized=False,
                membership__organization__name="ACME Inc.",
            ),
            id="PrescriberWithOrganization",
        ),
        pytest.param(
            partial(
                PrescriberFactory,
                membership__organization__authorized=True,
                membership__organization__name="ACME Inc.",
            ),
            id="AuthorizedPrescriber",
        ),
    ],
)
def test_navigation_authenticated(snapshot, client, user_factory):
    client.force_login(
        user_factory(
            for_snapshot=True,
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
        )
    )
    response = client.get(reverse("home:hp"), follow=True)
    assert str(parse_response_to_soup(response, "#nav-primary")) == snapshot(name="user menu")
    assert str(parse_response_to_soup(response, "#offcanvasNav")) == snapshot(name="navigation")
