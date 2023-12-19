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
        pytest.param(partial(EmployerFactory, with_company=True), id="Employer"),
        pytest.param(partial(LaborInspectorFactory, membership=True), id="LaborInspector"),
        pytest.param(PrescriberFactory, id="PrescriberWithoutOrganization"),
        pytest.param(
            partial(PrescriberFactory, membership__organization__authorized=False),
            id="PrescriberWithOrganization",
        ),
        pytest.param(
            partial(PrescriberFactory, membership__organization__authorized=True),
            id="AuthorizedPrescriber",
        ),
    ],
)
def test_navigation_authenticated(snapshot, client, user_factory):
    client.force_login(user_factory(for_snapshot=True, email="john.doe@example.com"))
    response = client.get(reverse("home:hp"), follow=True)
    assert str(parse_response_to_soup(response, "#nav-primary")) == snapshot
