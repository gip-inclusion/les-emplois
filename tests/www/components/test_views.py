from django.urls import reverse

from tests.utils.testing import parse_response_to_soup, pretty_indented


def test_alerts(client, snapshot):
    url = reverse("components:index")
    response = client.get(url)
    soup = parse_response_to_soup(response, selector="#alerts")
    assert pretty_indented(soup) == snapshot(name="alerts")
