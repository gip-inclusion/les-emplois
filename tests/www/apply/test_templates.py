import datetime
import random
from functools import partial

import pytest
from django.template import Context
from django.utils import timezone
from django.utils.html import escape
from freezegun import freeze_time
from pytest_django.asserts import assertInHTML, assertNotInHTML

from itou.eligibility.enums import (
    CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS,
    AdministrativeCriteriaKind,
    AdministrativeCriteriaLevel,
)
from itou.eligibility.tasks import certify_criterion_with_api_particulier
from itou.job_applications.enums import Origin
from itou.jobs.models import Appellation
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
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.testing import get_request, load_template
from tests.www.eligibility_views.utils import CERTIFIED_BADGE_HTML, NOT_CERTIFIED_BADGE_HTML


CERTIFIED_HELP_TEXT = "En savoir plus sur les badges de certification"


def situation_tooltip_text(kind):
    return (
        "Ces critères reflètent la situation du candidat lors de l’établissement du diagnostic"
        + (" ayant permis la délivrance d’un PASS IAE" if kind == "IAE" else "")
        + ", elle a peut-être changé depuis cette date."
    )


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
                "request": get_request(EmployerFactory()),
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
                "request": get_request(EmployerFactory()),
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
                "request": get_request(EmployerFactory()),
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
                "request": get_request(EmployerFactory()),
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
    ELIGIBILITY_TITLE = "Critères administratifs"

    @property
    def template(self):
        return load_template("apply/includes/eligibility_diagnosis.html")

    def default_params(self, diagnosis):
        job_application = JobApplicationFactory(
            eligibility_diagnosis=diagnosis,
            hiring_start_at=datetime.date(2024, 8, 3),
        )
        request = get_request(diagnosis.author)
        if diagnosis.is_from_employer:
            job_application.to_company = diagnosis.author_siae
            job_application.save()
        return {
            "eligibility_diagnosis": diagnosis,
            "request": request,
            "siae": job_application.to_company,
            "job_seeker": diagnosis.job_seeker,
            "itou_help_center_url": "https://help.com",
            "is_sent_by_authorized_prescriber": True,
        }

    def assert_criteria_name_in_rendered(self, diagnosis, rendered):
        if not diagnosis.administrative_criteria.all():
            assert escape("Le prescripteur habilité n’a pas renseigné de critères.") in rendered
        for criterion in diagnosis.administrative_criteria.all():
            assert escape(criterion.name) in rendered

    def test_diag_from_employer(self):
        diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            from_employer=True,
            criteria_kinds=[random.choice(list(AdministrativeCriteriaKind.for_iae()))],
        )

        is_sent_by_authorized_prescriber = random.choice([True, False])
        rendered = self.template.render(
            Context(
                self.default_params(diagnosis) | {"is_sent_by_authorized_prescriber": is_sent_by_authorized_prescriber}
            )
        )
        assert self.ELIGIBILITY_TITLE in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)

    def test_diag_from_prescriber(self):
        # Prescribers can make diagnoses without criteria
        criteria_kinds = [random.choice(list(AdministrativeCriteriaKind.for_iae()) + [None])]
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker__born_in_france=True, criteria_kinds=criteria_kinds, from_prescriber=True
        )

        is_sent_by_authorized_prescriber = random.choice([True, False])
        rendered = self.template.render(
            Context(
                self.default_params(diagnosis) | {"is_sent_by_authorized_prescriber": is_sent_by_authorized_prescriber}
            )
        )
        assert self.ELIGIBILITY_TITLE in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)

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
        assert self.ELIGIBILITY_TITLE not in rendered
        assert AdministrativeCriteriaLevel.LEVEL_1.label not in rendered
        assert "Le diagnostic d'éligibilité IAE de ce candidat a expiré" in rendered

    @pytest.mark.usefixtures("api_particulier_settings")
    def test_info_box(self, mocker):
        """Information box about why some criteria are certifiable."""
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED]["json"],
        )
        # No certifiable criteria
        diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.CAP_BEP],
        )
        rendered = self.template.render(Context(self.default_params(diagnosis)))
        assert CERTIFIED_HELP_TEXT not in rendered

        # Certifiable criteria, even if not certified.
        diagnosis = IAEEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        rendered = self.template.render(Context(self.default_params(diagnosis)))
        assert CERTIFIED_HELP_TEXT in rendered

        # Certifiable and certified.
        diagnosis = IAEEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        criterion = diagnosis.selected_administrative_criteria.get()
        certify_criterion_with_api_particulier(criterion)
        rendered = self.template.render(Context(self.default_params(diagnosis)))
        assert CERTIFIED_HELP_TEXT in rendered

        # Certifiable and certified as seen by a job seeker (on their dashboard).
        diagnosis = IAEEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        criterion = diagnosis.selected_administrative_criteria.get()
        certify_criterion_with_api_particulier(criterion)
        params = self.default_params(diagnosis)
        params.update(request=get_request(diagnosis.job_seeker))
        rendered = self.template.render(Context(params))
        assert CERTIFIED_HELP_TEXT not in rendered

    def test_situation_tooltip(self):
        """A tooltip explains that the situation may have changed since the diagnosis,
        do not display it to job seekers."""

        # Prescriber
        diagnosis = IAEEligibilityDiagnosisFactory(certifiable=True)
        rendered = self.template.render(Context(self.default_params(diagnosis)))
        assert situation_tooltip_text("IAE") in rendered

        # Employer
        diagnosis = IAEEligibilityDiagnosisFactory(certifiable=True, from_employer=True)
        rendered = self.template.render(Context(self.default_params(diagnosis)))
        assert situation_tooltip_text("IAE") in rendered

        # Job seeker (on their dashboard)
        diagnosis = IAEEligibilityDiagnosisFactory(certifiable=True)
        params = self.default_params(diagnosis)
        params.update(request=get_request(diagnosis.job_seeker))
        rendered = self.template.render(Context(params))
        assert situation_tooltip_text("IAE") not in rendered


class TestGEIQEligibilityDetail:
    ELIGIBILITY_TITLE = "Critères administratifs"

    @property
    def template(self):
        return load_template("apply/includes/geiq/geiq_diagnosis_details.html")

    def default_params_geiq(self, diagnosis):
        authorized_prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.first()
        # Use an authorized prescriber to not have to deal with the template heavily relying on user.is_employer
        request = get_request(authorized_prescriber)
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

    @pytest.mark.usefixtures("api_particulier_settings")
    @freeze_time("2024-10-04")
    def test_nominal_case(self, mocker):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"],
        )
        diagnosis = GEIQEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=[criteria_kind],
        )
        criterion = diagnosis.selected_administrative_criteria.get()
        self.create_job_application(diagnosis)
        certify_criterion_with_api_particulier(criterion)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis)))
        assert self.ELIGIBILITY_TITLE in rendered
        self.assert_criteria_name_in_rendered(diagnosis, rendered)

    @pytest.mark.usefixtures("api_particulier_settings")
    def test_info_box(self, mocker):
        """Information box about why some criteria are certifiable."""
        diagnosis = GEIQEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.CAP_BEP],
        )
        # No certifiable criteria
        self.create_job_application(diagnosis)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis)))
        assert CERTIFIED_HELP_TEXT not in rendered

        # Certifiable criteria but not certified.
        diagnosis = GEIQEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        self.create_job_application(diagnosis)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis)))
        assert CERTIFIED_HELP_TEXT in rendered

        # Certifiable and certified.
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED]["json"],
        )
        diagnosis = GEIQEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        criterion = diagnosis.selected_administrative_criteria.get()
        certify_criterion_with_api_particulier(criterion)
        self.create_job_application(diagnosis)
        rendered = self.template.render(Context(self.default_params_geiq(diagnosis)))
        assert CERTIFIED_HELP_TEXT in rendered

        # Certifiable and certified as seen by a job seeker (on their dashboard).
        diagnosis = GEIQEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        self.create_job_application(diagnosis)
        params = self.default_params_geiq(diagnosis)
        params.update(request=get_request(diagnosis.job_seeker))
        rendered = self.template.render(Context(params))
        assert CERTIFIED_HELP_TEXT not in rendered

    def test_situation_tooltip(self):
        """A tooltip explains that the situation may have changed since the diagnosis,
        do not display it to job seekers."""

        # Prescriber
        diagnosis = GEIQEligibilityDiagnosisFactory(certifiable=True, from_prescriber=True)
        job_app = self.create_job_application(diagnosis)
        params = self.default_params_geiq(diagnosis)
        params.update(request=get_request(diagnosis.author))
        rendered = self.template.render(Context(params))
        assert situation_tooltip_text("GEIQ") in rendered

        # Employer
        diagnosis = GEIQEligibilityDiagnosisFactory(certifiable=True, from_employer=True)
        self.create_job_application(diagnosis)
        params = self.default_params_geiq(diagnosis) | {
            "job_application": job_app
        }  # Employers need infos from job_application
        params.update(request=get_request(diagnosis.author))
        rendered = self.template.render(Context(params))
        assert situation_tooltip_text("GEIQ") in rendered

        # Job seeker (on their dashboard)
        diagnosis = GEIQEligibilityDiagnosisFactory(certifiable=True)
        params = self.default_params_geiq(diagnosis)
        params.update(request=get_request(diagnosis.job_seeker))
        rendered = self.template.render(Context(params))
        assert situation_tooltip_text("GEIQ") not in rendered


@pytest.mark.parametrize("factory", [IAEEligibilityDiagnosisFactory, GEIQEligibilityDiagnosisFactory])
class TestCertifiedBadge:
    def _render(self, **kwargs):
        kwargs.setdefault("request", {"from_authorized_prescriber": True})
        return load_template("apply/includes/selected_administrative_criteria_display.html").render(Context(kwargs))

    def test_certifiable_job_seeker_without_certifiable_criteria(self, factory):
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
        "user_factory,displayed",
        [
            (EmployerFactory, True),
            (partial(PrescriberFactory, membership__organization__authorized=True), True),
            (PrescriberFactory, False),
        ],
        ids=["employer", "authorized_prescriber", "prescriber"],
    )
    @pytest.mark.parametrize("is_certified", [True, False])
    def test_badge_is_only_displayed_to_employer_or_authorized_prescriber(
        self, factory, user_factory, displayed, is_certified
    ):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        diagnosis = factory(
            certifiable=True, criteria_kinds=[criteria_kind], from_prescriber=random.choice([None, True])
        )
        criterion = diagnosis.selected_administrative_criteria.get()
        criterion.certified = is_certified
        criterion.certified_at = timezone.now()

        request = get_request(user_factory())
        rendered = self._render(request=request, criterion=criterion)
        if displayed:
            expected, not_expected = (
                (CERTIFIED_BADGE_HTML, NOT_CERTIFIED_BADGE_HTML)
                if is_certified
                else (NOT_CERTIFIED_BADGE_HTML, CERTIFIED_BADGE_HTML)
            )
            assertInHTML(expected, rendered)
            assertNotInHTML(not_expected, rendered)
        else:
            assertNotInHTML(CERTIFIED_BADGE_HTML, rendered)
            assertNotInHTML(NOT_CERTIFIED_BADGE_HTML, rendered)
