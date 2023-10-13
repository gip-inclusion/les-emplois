from django.conf import Path
from django.template import Context, Template
from django.test.client import RequestFactory
from django.utils.html import escape

from itou.job_applications.enums import Origin
from itou.jobs.models import Appellation
from itou.utils.context_processors import expose_enums
from tests.job_applications.factories import JobApplicationSentByJobSeekerFactory, JobApplicationSentBySiaeFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import EmployerFactory, JobSeekerWithAddressFactory


def load_template(path):
    return Template((Path("itou/templates") / path).read_text())


def get_request():
    request = RequestFactory()
    request.user = EmployerFactory()
    return request


# Job applications list (SIAE)


def test_job_application_multiple_jobs():
    create_test_romes_and_appellations(["M1805"], appellations_per_rome=3)

    tmpl = load_template("apply/includes/list_card_body_siae.html")

    job_application = JobApplicationSentBySiaeFactory(
        selected_jobs=Appellation.objects.all(),
    )
    job_application.user_can_view_personal_information = True

    rendered = tmpl.render(
        Context(
            {
                "job_application": job_application,
                "request": get_request(),
                **expose_enums(),
            }
        )
    )

    # We have 3 selected_jobs, so we should display the first one
    # and 2 more
    assert "Voir les 3 postes" in rendered


def test_job_application_auto_prescription_badge_in_list():
    tmpl = load_template("apply/includes/list_card_body.html")
    job_application = JobApplicationSentBySiaeFactory()
    job_application.user_can_view_personal_information = True
    rendered = tmpl.render(
        Context(
            {
                "job_application": job_application,
                "request": get_request(),
                **expose_enums(),
            }
        )
    )

    assert "Auto-prescription" in rendered


def test_job_application_imported_from_pe_in_list():
    tmpl = load_template("apply/includes/list_card_body.html")
    job_application = JobApplicationSentBySiaeFactory(origin=Origin.PE_APPROVAL)
    job_application.user_can_view_personal_information = True
    rendered = tmpl.render(
        Context(
            {
                "job_application": job_application,
                "request": get_request(),
                **expose_enums(),
            }
        )
    )

    assert "Import agrément Pôle emploi" in rendered


def test_job_application_job_seeker_in_list():
    tmpl = load_template("apply/includes/list_card_body.html")
    job_application = JobApplicationSentByJobSeekerFactory()
    job_application.user_can_view_personal_information = True
    rendered = tmpl.render(
        Context(
            {
                "job_application": job_application,
                "request": get_request(),
                **expose_enums(),
            }
        )
    )

    assert "Le candidat lui-même" in rendered


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
