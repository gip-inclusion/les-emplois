import pytest
from django.contrib.sessions.middleware import SessionMiddleware
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory
from django.urls import reverse
from pytest_django.asserts import assertContains

from itou.utils import constants as global_constants
from itou.www.error import server_error
from tests.utils.tests import get_response_for_middlewaremixin


class FailingForm:
    def __init__(self):
        raise Exception("Something bad")


def test_error_handling(client, mocker):
    mocker.patch("itou.www.search.views.SiaeSearchForm", FailingForm)

    # Make sure we get the original exception
    # and not some "Undefined template variable" in layout/base.html template
    with pytest.raises(Exception, match="Something bad"):
        # We use this view and form because:
        # - it is simple
        # - we need to be able to patch something inside it to fail
        client.get(reverse("search:employers_home"))


def test_handler500_view():
    factory = RequestFactory()
    request = factory.get("/")
    request.user = None
    SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
    CsrfViewMiddleware(get_response_for_middlewaremixin).process_request(request)
    response = server_error(request)
    assertContains(
        response,
        "Notre équipe technique a été informée du problème et s'en occupera le plus rapidement possible.",
        status_code=500,
    )
    assertContains(response, global_constants.ITOU_HELP_CENTER_URL, status_code=500)
