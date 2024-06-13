import importlib
import io
import random
import re

import openpyxl
from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.test import Client, TestCase as BaseTestCase
from django.test.utils import TestContextDecorator
from pytest_django.asserts import assertContains, assertNotContains

from itou.common_apps.address.departments import DEPARTMENTS


# SAVEPOINT + RELEASE from the ATOMIC_REQUESTS transaction
BASE_NUM_QUERIES = 2


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


def remove_static_hash(content):
    return re.sub(r"\.[\da-f]{12}\.svg\b", ".svg", content)


def parse_response_to_soup(response, selector=None, no_html_body=False, replace_in_attr=None):
    soup = BeautifulSoup(response.content, "html5lib", from_encoding=response.charset or "utf-8")
    if no_html_body:
        # If the provided HTML does not contain <html><body> tags
        # html5lib will always add them around the response:
        # ignore them
        soup = soup.body
    if selector is not None:
        [soup] = soup.select(selector)
    title = soup.title
    if title:
        title.string = re.sub(r"\s+", " ", title.string)
    for csrf_token_input in soup.find_all("input", attrs={"name": "csrfmiddlewaretoken"}):
        csrf_token_input["value"] = "NORMALIZED_CSRF_TOKEN"
    if "nonce" in soup.attrs:
        soup["nonce"] = "NORMALIZED_CSP_NONCE"
    for csp_nonce_script in soup.find_all("script", {"nonce": True}):
        csp_nonce_script["nonce"] = "NORMALIZED_CSP_NONCE"
    for img in soup.find_all("img", attrs={"src": True}):
        img["src"] = remove_static_hash(img["src"])
    if replace_in_attr:
        replacements = [
            (
                replacement
                if isinstance(replacement, tuple)
                else ("href", str(replacement.pk), f"[PK of {type(replacement).__name__}]")
            )
            for replacement in replace_in_attr
        ]

        # Get the list of the attrs (deduplicated) we should search for replacement
        unique_attrs = set([replace_tuple[0] for replace_tuple in replacements])

        for attr in unique_attrs:
            # Search and replace in descendant nodes
            for links in soup.find_all(attrs={attr: True}):
                for _, from_str, to_str in replacements:
                    links.attrs.update({f"{attr}": links.attrs[attr].replace(from_str, to_str)})
            # Also replace attributes in the top node
            if attr in soup.attrs:
                for _, from_str, to_str in replacements:
                    soup.attrs.update({f"{attr}": soup.attrs[attr].replace(from_str, to_str)})
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


class ItouClient(NoInlineClient):
    def request(self, *args, **kwargs):
        with TestCase.captureOnCommitCallbacks(execute=True):
            return super().request(*args, **kwargs)


class TestCase(BaseTestCase):
    client_class = ItouClient


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


def assert_previous_step(response, url, back_to_list=False):
    previous_step = render_to_string("layout/previous_step.html", {"back_url": url})
    if back_to_list:
        assertContains(response, "Retour à la liste")
    else:
        assertNotContains(response, "Retour à la liste")
    assertContains(response, previous_step)


def create_fake_postcode():
    postcode = random.choice(list(DEPARTMENTS))
    if postcode in ["2A", "2B"]:
        postcode = "20"
    # add 3 numbers
    postcode += f"{int(random.randint(0, 999)):03}"
    # trunc to keep only 5 numbers, in case the department was 3 number long
    return postcode[:5]
