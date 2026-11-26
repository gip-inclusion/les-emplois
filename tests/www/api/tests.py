from django.urls import reverse

from tests.utils.testing import parse_response_to_soup, pretty_indented


def test_index(client, snapshot):
    response = client.get(reverse("api:index"))
    assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot
