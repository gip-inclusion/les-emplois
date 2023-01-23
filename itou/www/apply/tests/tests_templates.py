from django.conf import Path
from django.template import Context, Template
from django.test.client import RequestFactory
from django.utils.html import escape

from itou.job_applications.factories import JobApplicationSentBySiaeFactory
from itou.users.factories import JobSeekerWithAddressFactory, SiaeStaffFactory
from itou.utils.enums_context_processors import expose_enums


def load_template(path):
    return Template((Path("itou/templates") / path).read_text())


def get_request():
    request = RequestFactory()
    request.user = SiaeStaffFactory()
    return request


# Job applications list (SIAE)


def test_job_application_auto_prescription_badge_in_list():
    tmpl = load_template("apply/includes/list_card_body.html")
    rendered = tmpl.render(
        Context(
            {
                "job_application": JobApplicationSentBySiaeFactory(),
                "request": get_request(),
                **expose_enums(),
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
                **expose_enums(),
            }
        )
    )

    assert "Import agrément Pôle emploi" in rendered


# QPV / ZRR eligibility details


def test_known_criteria_template_with_no_criterion():
    tmpl = load_template("apply/includes/known_criteria.html")
    rendered = tmpl.render(Context({"job_seeker": JobSeekerWithAddressFactory()}))

    assert "est en QPV" not in rendered
    assert "est classée en ZRR" not in rendered
    assert "est partiellement classée en ZRR" not in rendered


def test_known_criteria_template_with_qpv_criterion():
    tmpl = load_template("apply/includes/known_criteria.html")
    job_seeker = JobSeekerWithAddressFactory(with_address_in_qpv=True)
    rendered = tmpl.render(Context({"job_seeker": job_seeker}))

    assert "est en QPV" in rendered
    assert "est classée en ZRR" not in rendered
    assert "est partiellement classée en ZRR" not in rendered
    assert escape(job_seeker.address_on_one_line) in rendered


def test_known_criteria_template_with_zrr_criterion():
    tmpl = load_template("apply/includes/known_criteria.html")
    job_seeker = JobSeekerWithAddressFactory(with_city_in_zrr=True)
    rendered = tmpl.render(Context({"job_seeker": job_seeker}))

    assert "est en QPV" not in rendered
    assert "est classée en ZRR" in rendered
    assert "est partiellement classée en ZRR" not in rendered
    assert escape(job_seeker.city) in rendered


def test_known_criteria_template_with_partial_zrr_criterion():
    tmpl = load_template("apply/includes/known_criteria.html")
    job_seeker = JobSeekerWithAddressFactory(with_city_partially_in_zrr=True)
    rendered = tmpl.render(Context({"job_seeker": job_seeker}))

    assert "est en QPV" not in rendered
    assert "est classée en ZRR" not in rendered
    assert "est partiellement classée en ZRR" in rendered
    assert escape(job_seeker.city) in rendered
