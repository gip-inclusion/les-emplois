from functools import partial

import pytest
from django.urls import reverse

from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerUserFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.test import parse_response_to_soup


def test_navigation_not_authenticated(snapshot, client):
    response = client.get(reverse("home:hp"), follow=True)
    assert str(parse_response_to_soup(response, "#nav-primary")) == snapshot


@pytest.mark.parametrize(
    "user_factory",
    [
        pytest.param(JobSeekerUserFactory, id="JobSeeker"),
        pytest.param(
            partial(
                EmployerFactory,
                with_company=True,
                with_company__company__name="ACME Inc.",
                with_company__company__not_in_territorial_experimentation=True,
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
                membership__organization__not_in_territorial_experimentation=True,
            ),
            id="PrescriberWithOrganization",
        ),
        pytest.param(
            lambda for_snapshot, first_name, last_name, email: PrescriberFactory(
                for_snapshot=for_snapshot,
                first_name=first_name,
                last_name=last_name,
                email=email,
                membership__organization=PrescriberOrganizationWithMembershipFactory(
                    authorized=True, name="ACME Inc.", not_in_territorial_experimentation=True
                ),
            ),
            id="PrescriberWithMultiMemberOrganization",
        ),
        pytest.param(
            partial(
                PrescriberFactory,
                membership__organization__authorized=True,
                membership__organization__name="ACME Inc.",
                membership__organization__not_in_territorial_experimentation=True,
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
