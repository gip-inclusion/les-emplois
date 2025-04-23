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
from itou.eligibility.utils import _criteria_for_display, geiq_criteria_for_display, iae_criteria_for_display
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
from tests.users.factories import EmployerFactory, JobSeekerFactory
from tests.utils.test import load_template
from tests.www.eligibility_views.utils import CERTIFIED_BADGE_HTML, NOT_CERTIFIED_BADGE_HTML


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
    rendered = tmpl.render(Context({"job_seeker": JobSeekerFactory(with_address=True)}))

    assert "est en QPV" not in rendered
    assert "est classée en ZRR" not in rendered
    assert "est partiellement classée en ZRR" not in rendered


@pytest.mark.ignore_unknown_variable_template_error("request")
def test_known_criteria_template_with_qpv_criterion():
    tmpl = load_template("apply/includes/known_criteria.html")
    job_seeker = JobSeekerFactory(with_address_in_qpv=True)
    rendered = tmpl.render(Context({"job_seeker": job_seeker}))

    assert "est en QPV" in rendered
    assert "est classée en ZRR" not in rendered
    assert "est partiellement classée en ZRR" not in rendered
    assert escape(job_seeker.address_on_one_line) in rendered


@pytest.mark.ignore_unknown_variable_template_error("request")
def test_known_criteria_template_with_zrr_criterion():
    tmpl = load_template("apply/includes/known_criteria.html")
    job_seeker = JobSeekerFactory(with_city_in_zrr=True)
    rendered = tmpl.render(Context({"job_seeker": job_seeker}))

    assert "est en QPV" not in rendered
    assert "est classée en ZRR" in rendered
    assert "est partiellement classée en ZRR" not in rendered
    assert escape(job_seeker.city) in rendered


@pytest.mark.ignore_unknown_variable_template_error("request")
def test_known_criteria_template_with_partial_zrr_criterion():
    tmpl = load_template("apply/includes/known_criteria.html")
    job_seeker = JobSeekerFactory(with_city_partially_in_zrr=True)
    rendered = tmpl.render(Context({"job_seeker": job_seeker}))

    assert "est en QPV" not in rendered
    assert "est classée en ZRR" not in rendered
    assert "est partiellement classée en ZRR" in rendered
    assert escape(job_seeker.city) in rendered


class TestIAEEligibilityDetail:
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
        request = RequestFactory()
        request.user = diagnosis.author
        request.from_authorized_prescriber = diagnosis.author.is_prescriber_with_authorized_org_memberships
        if diagnosis.is_from_employer:
            job_application.to_company = diagnosis.author_siae
            job_application.save()
        # This is the way it's set in views.
        diagnosis.criteria_display = iae_criteria_for_display(
            diagnosis, hiring_start_at=job_application.hiring_start_at
        )
        return {
            "eligibility_diagnosis": diagnosis,
            "request": request,
            "siae": job_application.to_company,
            "job_seeker": diagnosis.job_seeker,
            "itou_help_center_url": "https://help.com",
            "is_sent_by_authorized_prescriber": True,
        }

    def assert_criteria_name_in_rendered(self, diagnosis, rendered):
        for criterion in diagnosis.administrative_criteria.all():
            assert escape(criterion.name) in rendered

    def test_nominal_case(self):
        # Eligibility diagnosis made by an employer and job application not sent by an authorized prescriber.
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker__born_in_france=True,
            from_employer=True,
            criteria_kinds=[random.choice(list(AdministrativeCriteriaKind.for_iae()))],
        )
        criteria = diagnosis.selected_administrative_criteria.get().administrative_criteria

        rendered = self.template.render(
            Context(self.default_params(diagnosis) | {"is_sent_by_authorized_prescriber": False})
        )
        assert self.ELIGIBILITY_TITLE_FROM_EMPLOYER in rendered
        assert AdministrativeCriteriaLevel(criteria.level).label in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)

        # Eligibility diagnosis made by an employer but job application sent by an authorized prescriber.
        rendered = self.template.render(
            Context(self.default_params(diagnosis) | {"is_sent_by_authorized_prescriber": True})
        )
        assert self.ELIGIBILITY_TITLE_FROM_PRESCRIBER in rendered
        assert AdministrativeCriteriaLevel(criteria.level).label not in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)

    def test_diag_from_prescriber(self):
        # Diagnosis from prescriber but job application not sent by an authorized prescriber.
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker__born_in_france=True,
            criteria_kinds=[random.choice(list(AdministrativeCriteriaKind.for_iae()))],
            from_prescriber=True,
        )
        criteria = diagnosis.selected_administrative_criteria.get().administrative_criteria

        rendered = self.template.render(
            Context(self.default_params(diagnosis) | {"is_sent_by_authorized_prescriber": False})
        )
        assert self.ELIGIBILITY_TITLE_FROM_EMPLOYER in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assert AdministrativeCriteriaLevel(criteria.level).label in rendered

        # Diagnosis from prescriber and application sent by an authorized prescriber.
        rendered = self.template.render(
            Context(self.default_params(diagnosis) | {"is_sent_by_authorized_prescriber": True})
        )
        assert self.ELIGIBILITY_TITLE_FROM_PRESCRIBER in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)
        assert AdministrativeCriteriaLevel(criteria.level).label not in rendered

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


class TestGEIQEligibilityDetail:
    ELIGIBILITY_TITLE = "Situation administrative du candidat"

    @property
    def template(self):
        return load_template("apply/includes/geiq/geiq_diagnosis_details.html")

    def default_params_geiq(self, diagnosis, job_application):
        diagnosis.criteria_display = geiq_criteria_for_display(
            diagnosis, hiring_start_at=job_application.hiring_start_at
        )
        request = RequestFactory()
        # Force the value to not have to deal with the template heavily relying on user.is_employer
        request.from_authorized_prescriber = True
        return {
            "request": request,
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

    @freeze_time("2024-10-04")
    def test_nominal_case(self, mocker):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED],
        )
        diagnosis = GEIQEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=[criteria_kind],
        )
        job_application = self.create_job_application(diagnosis)
        certify_criteria(diagnosis)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis, job_application)))
        assert self.ELIGIBILITY_TITLE in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)

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


@pytest.mark.parametrize("factory", [IAEEligibilityDiagnosisFactory, GEIQEligibilityDiagnosisFactory])
class TestCertifiedBadge:
    def _render(self, **kwargs):
        kwargs.setdefault("request", {"from_authorized_prescriber": True})
        return load_template("apply/includes/selected_administrative_criteria_display.html").render(Context(kwargs))

    def test_certifiable_diagnosis_without_certifiable_criteria(self, factory):
        # No certifiable criteria
        diagnosis = factory(
            certifiable=True,
            criteria_kinds=[
                random.choice(list(AdministrativeCriteriaKind.common() - CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
            ],
        )

        criterion = diagnosis.selected_administrative_criteria.get()
        rendered = self._render(criterion=criterion)
        assert escape(criterion.administrative_criteria.name) in rendered
        assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
        assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)

    @pytest.mark.parametrize(
        "hiring_start_at,expected",
        [
            pytest.param(datetime.date(2024, 7, 31), False, id="Before validity period"),
            pytest.param(datetime.date(2024, 8, 1), True, id="Start of validity period"),
            pytest.param(datetime.date(2024, 11, 1), True, id="End of validity period"),
            pytest.param(datetime.date(2025, 11, 2), False, id="After validity period"),
        ],
    )
    def test_certifiable_diagnosis_with_certifiable_criteria(self, mocker, factory, hiring_start_at, expected):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        diagnosis = factory(certifiable=True, criteria_kinds=[criteria_kind])
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED],
        )
        certify_criteria(diagnosis)

        [criterion] = _criteria_for_display([diagnosis.selected_administrative_criteria.get()], hiring_start_at)
        rendered = self._render(criterion=criterion)
        assert escape(criterion.administrative_criteria.name) in rendered
        if expected:
            assertInHTML(CERTIFIED_BADGE_HTML, rendered)
            assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)
        else:
            assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
            assertInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)

    @pytest.mark.parametrize("employer", [True, False])
    @pytest.mark.parametrize("authorized_prescriber", [True, False])
    @pytest.mark.parametrize("is_considered_certified", [True, False])
    def test_badge_is_only_displayed_to_employer_or_authorized_prescriber(
        self, factory, employer, authorized_prescriber, is_considered_certified
    ):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        diagnosis = factory(
            certifiable=True, criteria_kinds=[criteria_kind], from_prescriber=random.choice([None, True])
        )
        criterion = diagnosis.selected_administrative_criteria.get()
        criterion.is_considered_certified = is_considered_certified

        rendered = self._render(
            request={"user": {"is_employer": employer}, "from_authorized_prescriber": authorized_prescriber},
            criterion=criterion,
        )
        if any([employer, authorized_prescriber]):
            expected, not_expected = (
                (CERTIFIED_BADGE_HTML, NOT_CERTIFIED_BADGE_HTML)
                if is_considered_certified
                else (NOT_CERTIFIED_BADGE_HTML, CERTIFIED_BADGE_HTML)
            )
            assertInHTML(expected, rendered)
            assertNotInHTML(not_expected, rendered)
        else:
            assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
            assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)
