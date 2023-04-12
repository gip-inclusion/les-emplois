import importlib
import io

import openpyxl
from bs4 import BeautifulSoup
from django.test import Client, TestCase as BaseTestCase
from django.test.utils import TestContextDecorator


def format_html(response, **selectors):
    """
    Formats an HTML document, ideal for inclusion in the expected outcome of a
    test.

    Heed the warning from
    https://www.crummy.com/software/BeautifulSoup/bs4/doc/#pretty-printing :

    > Since it adds whitespace (in the form of newlines), prettify() changes
      the meaning of an HTML document and should not be used to reformat one.
      The goal of prettify() is to help you visually understand the structure
      of the documents you work with.

    Prefer `assertHTMLEqual` and `assertContains(…, html=True)`.

    Nonetheless, this tool cuts boilerplate in capturing response output.
    """
    parser = BeautifulSoup(response.content, "html5lib")
    return [elt.prettify() for elt in parser.find_all(**selectors)]


def pprint_html(response, **selectors):
    print("\n\n".join(format_html(response, **selectors)))


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
