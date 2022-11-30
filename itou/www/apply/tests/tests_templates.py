from django.conf import Path
from django.template import Context, Template
from django.test.client import RequestFactory

from itou.job_applications.factories import JobApplicationSentBySiaeFactory
from itou.users.factories import UserFactory


def load_template(path):
    return Template((Path("itou/templates") / path).read_text())


def get_request():
    request = RequestFactory()
    request.user = UserFactory(is_siae_staff=True)
    return request


# Job applications list (SIAE)


def test_job_application_auto_prescription_badge_in_list():
    tmpl = load_template("apply/includes/list_card_body.html")
    rendered = tmpl.render(
        Context(
            {
                "job_application": JobApplicationSentBySiaeFactory(),
                "request": get_request(),
            }
        )
    )

    assert "Auto-prescription" in rendered


def test_job_application_imported_from_pe_in_list():
    tmpl = load_template("apply/includes/list_card_body.html")
    rendered = tmpl.render(
        Context(
            {
                "job_application": JobApplicationSentBySiaeFactory(created_from_pe_approval=True),
                "request": get_request(),
            }
        )
    )

    assert "Import agrément Pôle emploi" in rendered
