import dataclasses

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse
from django_htmx.middleware import HtmxDetails

from tests.utils.htmx.test import HtmxTestCase, assertSoupEqual, update_page_with_htmx
from tests.utils.test import parse_response_to_soup


# Unittest style
class HtmxRequestFactoryTest(HtmxTestCase):
    def test_get(self):
        response = self.htmx_client.get(reverse("search:employers_home"))
        assert response.status_code == 200
        assert isinstance(response.wsgi_request.htmx, HtmxDetails)
        assert response.wsgi_request.htmx.boosted is False

    def test_post(self):
        response = self.htmx_client.post(reverse("search:employers_home"))
        assert response.status_code == 200
        assert isinstance(response.wsgi_request.htmx, HtmxDetails)
        assert response.wsgi_request.htmx.boosted is False


# Pytest style
def test_htmx_client(htmx_client):
    response = htmx_client.get(reverse("search:employers_home"))
    assert response.status_code == 200
    assert isinstance(response.wsgi_request.htmx, HtmxDetails)
    assert response.wsgi_request.htmx.boosted is False


@dataclasses.dataclass
class FakeResponse:
    content: bytes
    charset: str = "utf-8"
    request: dict | None = None


def test_update_page_with_htmx():
    simulated_page = parse_response_to_soup(
        FakeResponse(
            b"""
              <html>
                <body>
                  <div id="main">
                    <div id="div-to-swap">
                      <form hx-post="/somewhere?with_query_string=" hx-swap="outerHTML" hx-target="#div-to-swap">
                        <input name="some_input"/>
                      </form>
                    </div>

                    <div id="other-div-for-oob-test"></div>
                  </div>
                </body>
              </html>
            """
        )
    )

    htmx_response = FakeResponse(
        b"""
          <div id="swapped-div">No more form !</div>
          <a href="#">Here is a link instead</a>
          <div id="other-div-for-oob-test" hx-swap-oob="true">OOB Swap successful</div>
        """,
        request={"PATH_INFO": "/somewhere", "REQUEST_METHOD": "POST", "QUERY_STRING": "with_query_string="},
    )

    update_page_with_htmx(simulated_page, "#div-to-swap > form", htmx_response)

    assertSoupEqual(
        simulated_page,
        BeautifulSoup(
            b"""
              <html>
                <body>
                  <div id="main">
                    <div id="swapped-div">No more form !</div>
                    <a href="#">Here is a link instead</a>

                    <div id="other-div-for-oob-test">OOB Swap successful</div>
                  </div>
                </body>
              </html>
            """,
            "html5lib",
        ),
    )


def test_update_page_with_htmx_wrong_method():
    simulated_page = parse_response_to_soup(
        FakeResponse(
            b"""
              <html>
                <body>
                  <div id="main">
                    <div id="div-to-swap">
                      <form hx-post="/somewhere?with_query_string=" hx-swap="outerHTML" hx-target="#div-to-swap">
                      </form>
                    </div>
                  </div>
                </body>
              </html>
            """
        )
    )

    with pytest.raises(ValueError, match="No hx-get attribute on provided HTMX element"):
        # Provided response comes from a GET but the htmx element has no hx-get element
        update_page_with_htmx(
            simulated_page,
            "#div-to-swap > form",
            FakeResponse(b"", request={"PATH_INFO": "/somewhere", "REQUEST_METHOD": "GET"}),
        )


def test_update_page_with_htmx_empty_attribute():
    # Empty hx-get which means we won't check it agains PATH_INFO
    simulated_page = parse_response_to_soup(
        FakeResponse(
            b"""
              <html>
                <body>
                  <div id="the-div" hx-target="this" hx-get hx-swap="outerHTML"/>
                </body>
              </html>
            """
        )
    )

    htmx_response = FakeResponse(
        b"",
        request={"PATH_INFO": "/somewhere", "REQUEST_METHOD": "GET", "QUERY_STRING": ""},
    )

    update_page_with_htmx(simulated_page, "#the-div", htmx_response)

    assertSoupEqual(
        simulated_page,
        BeautifulSoup(
            b"""
              <html>
                <body>
                </body>
              </html>
            """,
            "html5lib",
        ),
    )


def test_update_page_with_htmx_empty_response():
    simulated_page = parse_response_to_soup(
        FakeResponse(
            b"""
              <html>
                <body>
                  <div id="main">
                    <div id="div-to-swap">
                      <form hx-post="/somewhere?with_query_string=" hx-swap="outerHTML" hx-target="#div-to-swap">
                        <input name="some_input"/>
                      </form>
                    </div>

                    <div id="other-div-for-oob-test">
                    </div>
                  </div>
                </body>
              </html>
            """
        )
    )

    htmx_response = FakeResponse(
        b"""<div id="other-div-for-oob-test" hx-swap-oob="true">OOB Swap successful</div>""",
        request={"PATH_INFO": "/somewhere", "REQUEST_METHOD": "POST", "QUERY_STRING": "with_query_string="},
    )

    update_page_with_htmx(simulated_page, "#div-to-swap > form", htmx_response)

    assertSoupEqual(
        simulated_page,
        BeautifulSoup(
            b"""
              <html>
                <body>
                  <div id="main">
                    <div id="other-div-for-oob-test">OOB Swap successful</div>
                  </div>
                </body>
              </html>
            """,
            "html5lib",
        ),
    )


def test_update_page_with_htmx_hx_target_this():
    simulated_page = parse_response_to_soup(
        FakeResponse(
            b"""
              <html>
                <body>
                  <div id="main">
                    <div hx-target="this">
                      <form id="the-form" hx-post="/somewhere" hx-swap="outerHTML">
                        <input name="some_input"/>
                      </form>
                    </div>
                  </div>
                </body>
              </html>
            """
        )
    )

    htmx_response = FakeResponse(
        b"""<div id="new-div">Hello</div>""",
        request={"PATH_INFO": "/somewhere", "REQUEST_METHOD": "POST", "QUERY_STRING": ""},
    )

    update_page_with_htmx(simulated_page, "#the-form", htmx_response)

    assertSoupEqual(
        simulated_page,
        BeautifulSoup(
            b"""
              <html>
                <body>
                  <div id="main">
                    <div id="new-div">Hello</div>
                  </div>
                </body>
              </html>
            """,
            "html5lib",
        ),
    )


def test_assertSoupEqual():
    first_part = b"""<form hx-post="/somewhere" hx-swap="outerHTML" hx-target="this">
            <input name="csrfmiddlewaretoken" type="hidden" value="1234"/>
          </form>"""
    second_part = b"""<p>Bla bla bla</p>"""
    soup_1 = BeautifulSoup(first_part + second_part, "html5lib").body
    soup_2 = BeautifulSoup(first_part + b"\n\n" + second_part, "html5lib").body
    assertSoupEqual(soup_2, soup_1)
