import datetime
import random

import pytest
from django.template import Context
from django.test.client import RequestFactory
from django.utils.html import escape
from freezegun import freeze_time
from pytest_django.asserts import assertInHTML, assertNotInHTML

from itou.eligibility.enums import (
    CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS,
    AdministrativeCriteriaKind,
    AdministrativeCriteriaLevel,
)
from itou.eligibility.tasks import certify_criteria
from itou.job_applications.enums import Origin
from itou.jobs.models import Appellation
from itou.utils.context_processors import expose_enums
from itou.utils.mocks.api_particulier import RESPONSES, ResponseKind
from itou.www.apply.views.list_views import JobApplicationsDisplayKind, JobApplicationsListKind
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
    IAEEligibilityDiagnosisFactory,
)
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByCompanyFactory,
    JobApplicationSentByJobSeekerFactory,
)
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import EmployerFactory, JobSeekerUserFactory
from tests.utils.test import load_template


def get_request(path="/"):
    request = RequestFactory().get(path)
    request.user = EmployerFactory()
    return request


# Job applications list (company)


def test_job_application_multiple_jobs():
    create_test_romes_and_appellations(["M1805"], appellations_per_rome=3)

    tmpl = load_template("apply/includes/list_card_body.html")

    job_application = JobApplicationSentByCompanyFactory(
        selected_jobs=Appellation.objects.all(),
    )
    job_application.user_can_view_personal_information = True
    job_application.jobseeker_valid_eligibility_diagnosis = None

    rendered = tmpl.render(
        Context(
            {
                "job_application": job_application,
                "job_applications_list_kind": JobApplicationsListKind.RECEIVED,
                "JobApplicationsListKind": JobApplicationsListKind,
                "display_kind": JobApplicationsDisplayKind.LIST,
                "request": get_request(),
                **expose_enums(),
            }
        )
    )

    # We have 3 selected_jobs, so we should display the first one
    # and 2 more
    assertInHTML(
        f"""
        <button class="c-info__summary"
                data-bs-toggle="collapse"
                data-bs-target="#collapse-job-application-{job_application.pk}"
                aria-expanded="false"
                type="button"
                aria-controls="collapse-job-application-{job_application.pk}">
            <span>3 postes recherchés</span>
        </button>
        """,
        rendered,
    )


def test_job_application_auto_prescription_badge_in_list():
    tmpl = load_template("apply/includes/list_card_body.html")
    job_application = JobApplicationSentByCompanyFactory()
    job_application.user_can_view_personal_information = True
    job_application.jobseeker_valid_eligibility_diagnosis = None
    rendered = tmpl.render(
        Context(
            {
                "job_application": job_application,
                "job_applications_list_kind": JobApplicationsListKind.RECEIVED,
                "JobApplicationsListKind": JobApplicationsListKind,
                "display_kind": JobApplicationsDisplayKind.LIST,
                "request": get_request(),
                **expose_enums(),
            }
        )
    )

    assert "Auto-prescription" in rendered


def test_job_application_imported_from_pe_in_list():
    tmpl = load_template("apply/includes/list_card_body.html")
    job_application = JobApplicationSentByCompanyFactory(origin=Origin.PE_APPROVAL)
    job_application.user_can_view_personal_information = True
    job_application.jobseeker_valid_eligibility_diagnosis = None
    rendered = tmpl.render(
        Context(
            {
                "job_application": job_application,
                "job_applications_list_kind": JobApplicationsListKind.RECEIVED,
                "JobApplicationsListKind": JobApplicationsListKind,
                "display_kind": JobApplicationsDisplayKind.LIST,
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
    job_application.jobseeker_valid_eligibility_diagnosis = None
    rendered = tmpl.render(
        Context(
            {
                "job_application": job_application,
                "job_applications_list_kind": JobApplicationsListKind.RECEIVED,
                "JobApplicationsListKind": JobApplicationsListKind,
                "display_kind": JobApplicationsDisplayKind.LIST,
                "request": get_request(),
                **expose_enums(),
            }
        )
    )

    assert "Le candidat lui-même" in rendered


# QPV / ZRR eligibility details


@pytest.mark.ignore_unknown_variable_template_error("request")
def test_known_criteria_template_with_no_criterion():
    tmpl = load_template("apply/includes/known_criteria.html")
    rendered = tmpl.render(Context({"job_seeker": JobSeekerUserFactory(with_address=True)}))

    assert "est en QPV" not in rendered
    assert "est classée en ZRR" not in rendered
    assert "est partiellement classée en ZRR" not in rendered


@pytest.mark.ignore_unknown_variable_template_error("request")
def test_known_criteria_template_with_qpv_criterion():
    tmpl = load_template("apply/includes/known_criteria.html")
    job_seeker = JobSeekerUserFactory(with_address_in_qpv=True)
    rendered = tmpl.render(Context({"job_seeker": job_seeker}))

    assert "est en QPV" in rendered
    assert "est classée en ZRR" not in rendered
    assert "est partiellement classée en ZRR" not in rendered
    assert escape(job_seeker.address_on_one_line) in rendered


@pytest.mark.ignore_unknown_variable_template_error("request")
def test_known_criteria_template_with_zrr_criterion():
    tmpl = load_template("apply/includes/known_criteria.html")
    job_seeker = JobSeekerUserFactory(with_city_in_zrr=True)
    rendered = tmpl.render(Context({"job_seeker": job_seeker}))

    assert "est en QPV" not in rendered
    assert "est classée en ZRR" in rendered
    assert "est partiellement classée en ZRR" not in rendered
    assert escape(job_seeker.city) in rendered


@pytest.mark.ignore_unknown_variable_template_error("request")
def test_known_criteria_template_with_partial_zrr_criterion():
    tmpl = load_template("apply/includes/known_criteria.html")
    job_seeker = JobSeekerUserFactory(with_city_partially_in_zrr=True)
    rendered = tmpl.render(Context({"job_seeker": job_seeker}))

    assert "est en QPV" not in rendered
    assert "est classée en ZRR" not in rendered
    assert "est partiellement classée en ZRR" in rendered
    assert escape(job_seeker.city) in rendered


CERTIFIED_BADGE_HTML = """\
<span class="badge badge-xs rounded-pill bg-info-lighter text-info ms-3">
    <i class="ri-verified-badge-fill" aria-hidden="true"></i>
    Certifié</span>"""
NOT_CERTIFIED_BADGE_HTML = """\
<span class="badge badge-xs rounded-pill bg-warning-lighter text-warning ms-3">
    <i class="ri-error-warning-fill" aria-hidden="true"></i>
    Non certifié</span>"""


class TestCertifiedBadgeIae:
    ELIGIBILITY_TITLE_FROM_PRESCRIBER = "Situation administrative du candidat"
    ELIGIBILITY_TITLE_FROM_EMPLOYER = "Critères administratifs"

    @property
    def template(self):
        return load_template("apply/includes/eligibility_diagnosis.html")

    def default_params(self, diagnosis):
        job_application = JobApplicationFactory(
            eligibility_diagnosis=diagnosis,
            hiring_start_at=datetime.date(2024, 8, 3),
        )
        if diagnosis.is_from_employer:
            job_application.to_company = diagnosis.author_siae
            job_application.save()
        # This is the way it's set in views.
        diagnosis.criteria_display = diagnosis.get_criteria_display_qs(hiring_start_at=job_application.hiring_start_at)
        return {
            "eligibility_diagnosis": diagnosis,
            "request": RequestFactory(),
            "siae": job_application.to_company,
            "job_seeker": diagnosis.job_seeker,
            "itou_help_center_url": "https://help.com",
            "is_sent_by_authorized_prescriber": True,
        }

    def assert_criteria_name_in_rendered(self, diagnosis, rendered):
        for criterion in diagnosis.administrative_criteria.all():
            assert escape(criterion.name) in rendered

    def test_nominal_case(self, mocker):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        # Eligibility diagnosis made by an employer and job application not sent by an authorized prescriber.
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED],
        )
        diagnosis = IAEEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[criteria_kind])
        criteria = diagnosis.selected_administrative_criteria.get().administrative_criteria

        certify_criteria(diagnosis)

        rendered = self.template.render(
            Context(self.default_params(diagnosis) | {"is_sent_by_authorized_prescriber": False})
        )
        assert self.ELIGIBILITY_TITLE_FROM_EMPLOYER in rendered
        assert AdministrativeCriteriaLevel(criteria.level).label in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assertInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)

        # Eligibility diagnosis made by an employer but job application sent by an authorized prescriber.
        rendered = self.template.render(
            Context(self.default_params(diagnosis) | {"is_sent_by_authorized_prescriber": True})
        )
        assert self.ELIGIBILITY_TITLE_FROM_PRESCRIBER in rendered
        assert AdministrativeCriteriaLevel(criteria.level).label not in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assertInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)

    def test_diag_from_prescriber(self, mocker):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        # Diagnosis from prescriber but job application not sent by an authorized prescriber.
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED],
        )
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker__born_in_france=True,
            criteria_kinds=[criteria_kind],
            from_prescriber=True,
        )
        criteria = diagnosis.selected_administrative_criteria.get().administrative_criteria

        certify_criteria(diagnosis)

        rendered = self.template.render(
            Context(self.default_params(diagnosis) | {"is_sent_by_authorized_prescriber": False})
        )
        assert self.ELIGIBILITY_TITLE_FROM_EMPLOYER in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)
        assert AdministrativeCriteriaLevel(criteria.level).label in rendered

        # Diagnosis from prescriber and application sent by an authorized prescriber.
        rendered = self.template.render(
            Context(self.default_params(diagnosis) | {"is_sent_by_authorized_prescriber": True})
        )
        assert self.ELIGIBILITY_TITLE_FROM_PRESCRIBER in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)
        assert AdministrativeCriteriaLevel(criteria.level).label not in rendered

    def test_no_certifiable_criteria(self):
        # No certifiable criteria
        diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.CAP_BEP],
        )

        rendered = self.template.render(Context(self.default_params(diagnosis)))
        assert self.ELIGIBILITY_TITLE_FROM_PRESCRIBER in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)

    def test_criteria_not_certified(self):
        diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.AAH],
        )
        rendered = self.template.render(Context(self.default_params(diagnosis)))
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)

    def test_expired_diagnosis(self):
        # Expired Eligibility Diagnosis
        diagnosis = IAEEligibilityDiagnosisFactory(expired=True, from_prescriber=True)
        rendered = self.template.render(
            Context(
                self.default_params(diagnosis)
                | {
                    "expired_eligibility_diagnosis": diagnosis,
                }
            )
        )
        assert self.ELIGIBILITY_TITLE_FROM_PRESCRIBER not in rendered
        assert AdministrativeCriteriaLevel.LEVEL_1.label not in rendered
        assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)
        assert "Le diagnostic d'éligibilité IAE de ce candidat a expiré" in rendered

    def test_info_box(self, mocker):
        """Information box about why some criteria are certifiable."""
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED],
        )
        certified_help_text = "Pourquoi certains critères peuvent-ils être certifiés"
        # No certifiable criteria
        diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.CAP_BEP],
        )
        rendered = self.template.render(Context(self.default_params(diagnosis)))
        assert certified_help_text not in rendered

        # Certifiable criteria, even if not certified.
        diagnosis = IAEEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        rendered = self.template.render(Context(self.default_params(diagnosis)))
        assert certified_help_text in rendered

        # Certifiable and certified.
        diagnosis = IAEEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        certify_criteria(diagnosis)
        rendered = self.template.render(Context(self.default_params(diagnosis)))
        assert certified_help_text in rendered


class TestCertifiedBadgeGEIQ:
    ELIGIBILITY_TITLE = "Situation administrative du candidat"

    @property
    def template(self):
        return load_template("apply/includes/geiq/geiq_diagnosis_details.html")

    def default_params_geiq(self, diagnosis, job_application):
        diagnosis.criteria_display = diagnosis.get_criteria_display_qs(hiring_start_at=job_application.hiring_start_at)
        return {
            "request": RequestFactory(),
            "diagnosis": diagnosis,
            "itou_help_center_url": "https://help.com",
        }

    def assert_criteria_name_in_rendered(self, diagnosis, rendered):
        for criterion in diagnosis.administrative_criteria.all():
            assert escape(criterion.name) in rendered

    def create_job_application(self, diagnosis, hiring_start_at=None):
        if not hiring_start_at:
            hiring_start_at = datetime.date(2024, 8, 3)
        job_application = JobApplicationFactory(
            with_geiq_eligibility_diagnosis=True,
            geiq_eligibility_diagnosis=diagnosis,
            hiring_start_at=hiring_start_at,
        )
        if diagnosis.is_from_employer:
            job_application.to_company = diagnosis.author_geiq
            job_application.save()
        return job_application

    @pytest.mark.ignore_unknown_variable_template_error("request")
    def test_diag_from_prescriber(self, mocker):
        """
        Nominal case
        Eligibility diagnosis is from a prescriber.
        Don't display a "certified" badge.
        """
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED],
        )
        diagnosis = GEIQEligibilityDiagnosisFactory(
            job_seeker__born_in_france=True,
            criteria_kinds=[criteria_kind],
            from_prescriber=True,
        )
        job_application = self.create_job_application(diagnosis)
        certify_criteria(diagnosis)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis, job_application)))
        assert self.ELIGIBILITY_TITLE in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)

    @freeze_time("2024-10-04")
    def test_nominal_case(self, mocker):
        """
        Eligibility diagnosis is from an employer.
        Display a "certified" badge.
        """
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED],
        )
        diagnosis = GEIQEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[criteria_kind])
        job_application_with_certified_criteria = self.create_job_application(diagnosis)
        certify_criteria(diagnosis)
        rendered = self.template.render(
            Context(self.default_params_geiq(diagnosis, job_application_with_certified_criteria))
        )
        assert self.ELIGIBILITY_TITLE in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assertInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)

    @freeze_time("2024-10-04")
    def test_hiring_date_nearly_out_of_boundaries(self, mocker):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        # Hiring start at starts 20 days after the certification period ending.
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED],
        )
        diagnosis = GEIQEligibilityDiagnosisFactory(criteria_kinds=[criteria_kind], certifiable=True)
        job_application = self.create_job_application(diagnosis, hiring_start_at=datetime.date(2024, 11, 30))
        certify_criteria(diagnosis)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis, job_application)))
        assert self.ELIGIBILITY_TITLE in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assertInHTML(CERTIFIED_BADGE_HTML, rendered)

    @freeze_time("2024-08-01")
    def test_hiring_date_out_of_boundaries(self, mocker):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        # Hiring start at starts more than 90 days after the certification period ending.
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED],
        )
        diagnosis = GEIQEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[criteria_kind])
        job_application = self.create_job_application(diagnosis, hiring_start_at=datetime.date(2025, 2, 28))
        certify_criteria(diagnosis)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis, job_application)))
        assert self.ELIGIBILITY_TITLE in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)

    def test_no_certified_criteria(self):
        # No certified criteria
        diagnosis = GEIQEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.CAP_BEP],
        )
        job_application = self.create_job_application(diagnosis)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis, job_application)))
        assert self.ELIGIBILITY_TITLE in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)

    def test_criteria_not_certified(self):
        diagnosis = GEIQEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.AAH],
        )
        job_application = self.create_job_application(diagnosis)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis, job_application)))
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)

    def test_info_box(self, mocker):
        """Information box about why some criteria are certifiable."""
        certified_help_text = "Pourquoi certains critères peuvent-ils être certifiés"
        diagnosis = GEIQEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.CAP_BEP],
        )
        # No certifiable criteria
        job_application = self.create_job_application(diagnosis)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis, job_application)))
        assert certified_help_text not in rendered

        # Certifiable criteria but not certified.
        diagnosis = GEIQEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        job_application = self.create_job_application(diagnosis)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis, job_application)))
        assert certified_help_text in rendered

        # Certifiable and certified.
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED],
        )
        diagnosis = GEIQEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        certify_criteria(diagnosis)
        job_application = self.create_job_application(diagnosis)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis, job_application)))
        assert certified_help_text in rendered
