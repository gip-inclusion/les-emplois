from bs4 import BeautifulSoup

from itou.emails.utils import get_email_message


def parse_html(html_alternative):
    return BeautifulSoup(html_alternative, "html5lib")


def test_renders_markdown(snapshot, template_dir_fixture):
    email = get_email_message(["manuel@calavera.me"], {}, "subject.txt", "markdown_body.md")
    [html_attachment] = email.alternatives
    html = parse_html(html_attachment.content)
    assert html.prettify() == snapshot()


def test_domain_allowlist(settings, template_dir_fixture):
    settings.ALLOWED_HOSTS = ["example.org"]
    email = get_email_message(["manuel@calavera.me"], {}, "subject.txt", "domain_allowlist_body.md")
    [html_attachment] = email.alternatives
    html = parse_html(html_attachment.content)
    assert [str(link) for link in html.find_all("a")] == [
        '<a href="https://diagoriente.beta.gouv.fr/">https://diagoriente.beta.gouv.fr/</a>',
        '<a href="https://example.org/">https://example.org/</a>',
    ]


def test_html_markup_removed(snapshot, template_dir_fixture):
    email = get_email_message(["manuel@calavera.me"], {}, "subject.txt", "html_body.md")
    [html_attachment] = email.alternatives
    html = parse_html(html_attachment.content)
    assert html.prettify() == snapshot()
