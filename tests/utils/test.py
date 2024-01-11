import importlib
import io
from typing import NamedTuple

import openpyxl
from bs4 import BeautifulSoup
from django.contrib.messages import DEFAULT_LEVELS, get_messages
from django.http import HttpResponse
from django.test import Client, TestCase as BaseTestCase
from django.test.utils import TestContextDecorator


# SAVEPOINT + RELEASE from the ATOMIC_REQUESTS transaction
BASE_NUM_QUERIES = 2


class Message(NamedTuple):
    level: int
    message: str


LEVEL_TO_NAME = {intlevel: name for name, intlevel in DEFAULT_LEVELS.items()}


def assertMessagesFromRequest(request, expected_messages: list[Message]):
    request_messages = get_messages(request)
    for message, (expected_level, expected_msg) in zip(request_messages, expected_messages, strict=True):
        msg_levelname = LEVEL_TO_NAME.get(message.level, message.level)
        expected_levelname = LEVEL_TO_NAME.get(expected_level, expected_level)
        assert (msg_levelname, message.message) == (expected_levelname, expected_msg)


def assertMessages(response: HttpResponse, expected_messages: list[Message]):
    assertMessagesFromRequest(response.wsgi_request, expected_messages)


def pprint_html(response, **selectors):
    """
    Pretty-print HTML responses (or fragment selected with :arg:`selector`)

    Heed the warning from
    https://www.crummy.com/software/BeautifulSoup/bs4/doc/#pretty-printing :

    > Since it adds whitespace (in the form of newlines), prettify() changes
      the meaning of an HTML document and should not be used to reformat one.
      The goal of prettify() is to help you visually understand the structure
      of the documents you work with.

    Use `snapshot`s, `assertHTMLEqual` and `assertContains(…, html=True)` to
    make assertions.
    """
    parser = BeautifulSoup(response.content, "html5lib")
    print("\n\n".join([elt.prettify() for elt in parser.find_all(**selectors)]))


def parse_response_to_soup(response, selector=None, no_html_body=False, replace_in_href=None):
    soup = BeautifulSoup(response.content, "html5lib", from_encoding=response.charset or "utf-8")
    if no_html_body:
        # If the provided HTML does not contain <html><body> tags
        # html5lib will always add them around the response:
        # ignore them
        soup = soup.body
    if selector is not None:
        [soup] = soup.select(selector)
    for csrf_token_input in soup.find_all("input", attrs={"name": "csrfmiddlewaretoken"}):
        csrf_token_input["value"] = "NORMALIZED_CSRF_TOKEN"
    if "nonce" in soup.attrs:
        soup["nonce"] = "NORMALIZED_CSP_NONCE"
    for csp_nonce_script in soup.find_all("script", {"nonce": True}):
        csp_nonce_script["nonce"] = "NORMALIZED_CSP_NONCE"
    if replace_in_href:
        for links in soup.find_all(attrs={"href": True}):
            for obj in replace_in_href:
                links.attrs["href"] = links.attrs["href"].replace(str(obj.pk), f"[PK of {type(obj).__name__}]")
    return soup


class NoInlineClient(Client):
    def request(self, **request):
        response = super().request(**request)
        content_type = response["Content-Type"].split(";")[0]
        if content_type == "text/html" and response.content:
            content = response.content.decode(response.charset)
            assert " onclick=" not in content
            assert " onbeforeinput=" not in content
            assert " onbeforeinput=" not in content
            assert " onchange=" not in content
            assert " oncopy=" not in content
            assert " oncut=" not in content
            assert " ondrag=" not in content
            assert " ondragend=" not in content
            assert " ondragenter=" not in content
            assert " ondragleave=" not in content
            assert " ondragover=" not in content
            assert " ondragstart=" not in content
            assert " ondrop=" not in content
            assert " oninput=" not in content
            assert "<script>" not in content
        return response


class TestCase(BaseTestCase):
    client_class = NoInlineClient


class reload_module(TestContextDecorator):
    def __init__(self, module):
        self._module = module
        self._original_values = {key: getattr(module, key) for key in dir(module) if not key.startswith("__")}
        super().__init__()

    def enable(self):
        importlib.reload(self._module)

    def disable(self):
        for key, value in self._original_values.items():
            setattr(self._module, key, value)


def get_rows_from_streaming_response(response):
    """Helper to read streamed XLSX files in tests"""

    content = b"".join(response.streaming_content)
    workbook = openpyxl.load_workbook(io.BytesIO(content))
    worksheet = workbook.active
    return [[cell.value or "" for cell in row] for row in worksheet.rows]
