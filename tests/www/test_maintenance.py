from django.urls import reverse
from pytest_django.asserts import assertNumQueries

from tests.users.factories import JobSeekerFactory
from tests.utils.test import parse_response_to_soup, pretty_indented


def test_maintenance(client, settings, snapshot):
    # Maintenance mode
    settings.MAINTENANCE_MODE = True
    with assertNumQueries(0):
        response = client.get(reverse("dashboard:index"))
    assert pretty_indented(parse_response_to_soup(response, "main")) == snapshot(name="no_description")

    with assertNumQueries(0):
        response = client.get(reverse("dashboard:index"), headers={"Content-Type": "application/json"})
    assert response.json() == {"error": "maintenance en cours"}
    assert response.status_code == 503

    # With description
    settings.MAINTENANCE_DESCRIPTION = "Oups"
    with assertNumQueries(0):
        response = client.get(reverse("dashboard:index"))
    assert pretty_indented(parse_response_to_soup(response, "main")) == snapshot(name="with_description")

    with assertNumQueries(0):
        response = client.get(reverse("dashboard:index"), headers={"Content-Type": "application/json"})
    assert response.json() == {"error": "Oups"}
    assert response.status_code == 503

    # Still no queries if the user was logged in
    user = JobSeekerFactory()
    client.force_login(user)
    with assertNumQueries(0):
        response = client.get(reverse("dashboard:index"))
