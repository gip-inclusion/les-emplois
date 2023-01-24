from bs4 import BeautifulSoup
from django.test import Client, TestCase as BaseTestCase


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
