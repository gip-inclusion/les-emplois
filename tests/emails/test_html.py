from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from itou.utils.emails import get_email_message


@pytest.fixture(autouse=True)
def template_dir_fixture(settings):
    [template_engine] = settings.TEMPLATES
    template_engine["DIRS"].insert(0, str(Path(__file__).parent / "templates"))
    settings.TEMPLATES = [template_engine]


def parse_html(html_alternative):
    return BeautifulSoup(html_alternative, "html5lib")


def test_renders_markdown(snapshot):
    email = get_email_message(["manuel@calavera.me"], {}, "subject.txt", "markdown_body.md")
    [html_attachment] = email.alternatives
    html = parse_html(html_attachment.content)
    assert html.prettify() == snapshot()


@pytest.mark.parametrize(
    "template_name, expected",
    [
        pytest.param("unknown_domain", [], id="unknown_domain"),
        pytest.param(
            "known_domain",
            ['<a href="https://diagoriente.beta.gouv.fr/">https://diagoriente.beta.gouv.fr/</a>'],
            id="known_domain",
        ),
    ],
)
def test_domain_allowlist(template_name, expected):
    email = get_email_message(["manuel@calavera.me"], {}, "subject.txt", f"{template_name}_body.md")
    [html_attachment] = email.alternatives
    html = parse_html(html_attachment.content)
    assert [str(link) for link in html.find_all("a")] == expected


def test_html_markup_removed(snapshot):
    email = get_email_message(["manuel@calavera.me"], {}, "subject.txt", "html_body.md")
    [html_attachment] = email.alternatives
    html = parse_html(html_attachment.content)
    assert html.prettify() == snapshot()
