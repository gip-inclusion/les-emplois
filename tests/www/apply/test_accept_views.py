import datetime
import random
import uuid
from itertools import product

import pytest
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.db.models import Exists, OuterRef, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import (
    assertContains,
    assertFormError,
    assertMessages,
    assertNotContains,
    assertRedirects,
)

from itou.approvals.models import Approval, Suspension
from itou.asp.models import Commune, Country
from itou.cities.models import City
from itou.companies.enums import CompanyKind, ContractType, JobDescriptionSource
from itou.eligibility.enums import CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS, AdministrativeCriteriaKind
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQSelectedAdministrativeCriteria
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.enums import JobApplicationState, QualificationLevel, QualificationType
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.jobs.models import Appellation
from itou.users.enums import IdentityCertificationAuthorities, LackOfNIRReason, LackOfPoleEmploiId, UserKind
from itou.users.models import IdentityCertification, User
from itou.utils.mocks.address_format import mock_get_first_geocoding_data, mock_get_geocoding_data_by_ban_api_resolved
from itou.utils.mocks.api_particulier import RESPONSES, ResponseKind
from itou.utils.models import InclusiveDateRange
from itou.utils.urls import get_zendesk_form_url
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.apply.forms import AcceptForm
from itou.www.apply.views.accept_views import (
    ACCEPT_SESSION_KIND,
    initialize_accept_session,
)
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.cities.factories import create_city_geispolsheim
from tests.companies.factories import CompanyFactory, JobDescriptionFactory, SiaeConventionFactory
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
    IAEEligibilityDiagnosisFactory,
    IAESelectedAdministrativeCriteriaFactory,
)
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByJobSeekerFactory,
)
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users import constants as users_test_constants
from tests.users.factories import JobSeekerFactory, PrescriberFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import (
    get_session_name,
    parse_response_to_soup,
)


NIR_FIELD_ID = 'id="id_nir"'

BACK_BUTTON_ARIA_LABEL = "Retourner à l’étape précédente"
LINK_RESET_MARKUP = (
    '<a href="%s" class="btn btn-link btn-ico ps-lg-0 w-100 w-lg-auto"'
    ' aria-label="Annuler la saisie de ce formulaire">'
)
CONFIRM_RESET_MARKUP = '<a href="%s" class="btn btn-sm btn-danger">Confirmer l\'annulation</a>'
NEXT_BUTTON_MARKUP = (
    '<button type="submit" class="btn btn-block btn-primary" aria-label="Passer à l’étape suivante">'
    "<span>Suivant</span>"
    "</button>"
)


class TestProcessAcceptViewsInWizard:
    BIRTH_COUNTRY_LABEL = "Pays de naissance"
    BIRTH_PLACE_LABEL = "Commune de naissance"
    OPEN_JOBS_TEXT = "Postes ouverts au recrutement"
    CLOSED_JOBS_TEXT = "Postes fermés au recrutement"
    SPECIFY_JOB_TEXT = "Préciser le nom du poste (code ROME)"

    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        self.company = CompanyFactory(
            with_membership=True, with_jobs=True, name="La brigade - entreprise par défaut", subject_to_iae_rules=True
        )
        self.job_seeker = JobSeekerFactory(
            jobseeker_profile__with_pole_emploi_id=True,
            with_ban_api_mocked_address=True,
        )

        settings.API_GEOPF_BASE_URL = "http://ban-api"
        settings.TALLY_URL = "https://tally.so"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

    def create_job_application(self, **kwargs):
        kwargs = {
            "selected_jobs": self.company.jobs.all(),
            "state": JobApplicationState.PROCESSING,
            "job_seeker": self.job_seeker,
            "to_company": self.company,
            "hiring_end_at": None,
        } | kwargs
        return JobApplicationSentByJobSeekerFactory(**kwargs)

    def _accept_jobseeker_post_data(self, job_application, post_data=None):
        if post_data is not None:
            return post_data
        job_seeker = job_application.job_seeker
        # JobSeekerPersonalDataForm
        birth_place = (
            Commune.objects.filter(
                start_date__lte=job_seeker.jobseeker_profile.birthdate,
                end_date__gte=job_seeker.jobseeker_profile.birthdate,
            )
            .first()
            .pk
        )
        return {
            "birthdate": job_seeker.jobseeker_profile.birthdate,
            "birth_country": Country.FRANCE_ID,
            "birth_place": birth_place,
        }

    def _accept_contract_post_data(self, job_application, post_data=None):
        extra_post_data = post_data or {}
        # AcceptForm
        job_description = job_application.selected_jobs.first()
        hiring_start_at = timezone.localdate()
        hiring_end_at = Approval.get_default_end_date(hiring_start_at)
        accept_default_fields = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "answer": "",
            "hired_job": job_description.pk,
        }
        # GEIQ-only mandatory fields
        if job_application.to_company.kind == CompanyKind.GEIQ:
            accept_default_fields |= {
                "prehiring_guidance_days": 10,
                "contract_type": ContractType.APPRENTICESHIP,
                "nb_hours_per_week": 10,
                "qualification_type": QualificationType.CQP,
                "qualification_level": QualificationLevel.LEVEL_4,
                "planned_training_hours": 20,
            }
        return accept_default_fields | extra_post_data

    def get_job_seeker_info_step_url(self, session_uuid):
        return reverse("apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid})

    def get_contract_info_step_url(self, session_uuid):
        return reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid})

    def get_confirm_step_url(self, session_uuid):
        return reverse("apply:accept_confirmation", kwargs={"session_uuid": session_uuid})

    def start_accept_job_application(self, client, job_application, next_url=None):
        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept, data={"next_url": next_url} if next_url else {})
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        assertRedirects(
            response,
            self.get_job_seeker_info_step_url(session_uuid),
            fetch_redirect_response=False,  # Either a 302 or a 200
        )
        return session_uuid

    def fill_job_seeker_info_step(self, client, job_application, session_uuid, post_data=None):
        url_job_seeker_info = self.get_job_seeker_info_step_url(session_uuid)
        post_data = self._accept_jobseeker_post_data(job_application=job_application, post_data=post_data)
        return client.post(url_job_seeker_info, data=post_data)

    def fill_contract_info_step(
        self,
        client,
        job_application,
        session_uuid,
        post_data=None,
        assert_successful=True,
        reset_url=None,
        with_previous_step=True,
    ):
        """
        This is not a test. It's a shortcut to process "apply:start-accept" wizard steps:
        - GET: start the accept process and redirect to job seeker infos step
        - POST: handle job seeker infos step
        - POST: show the confirmation modal
        - POST: hide the modal and redirect to the next url.

        """
        if reset_url is None:
            reset_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        contract_info_url = self.get_contract_info_step_url(session_uuid)
        response = client.get(contract_info_url)
        if with_previous_step:
            assertContains(response, CONFIRM_RESET_MARKUP % reset_url)
            assertContains(response, BACK_BUTTON_ARIA_LABEL)
        else:
            assertContains(response, LINK_RESET_MARKUP % reset_url)
            assertNotContains(response, BACK_BUTTON_ARIA_LABEL)

        post_data = self._accept_contract_post_data(job_application=job_application, post_data=post_data)
        response = client.post(contract_info_url, data=post_data)
        if assert_successful:
            assertRedirects(response, self.get_confirm_step_url(session_uuid), fetch_redirect_response=False)
        return response

    def confirm_step(self, client, session_uuid, *, reset_url, assert_successful=True):
        url_confirm = self.get_confirm_step_url(session_uuid)
        response = client.get(url_confirm)
        assertContains(response, "Confirmer l’embauche", count=3)  # alert + button label + button aria-label
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url)
        assertContains(response, BACK_BUTTON_ARIA_LABEL)
        response = client.post(url_confirm)
        if assert_successful:
            assertRedirects(
                response,
                reset_url,
                fetch_redirect_response=False,
            )
        return response

    _nominal_cases = list(
        product(
            [Approval.get_default_end_date(timezone.localdate()), None],
            JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES,
        )
    )

    @pytest.mark.parametrize(
        "hiring_end_at,state",
        _nominal_cases,
        ids=[state + ("_no_end_date" if not end_at else "") for end_at, state in _nominal_cases],
    )
    def test_nominal_iae_case(self, client, hiring_end_at, state):
        today = timezone.localdate()
        job_application = self.create_job_application(state=state)
        previous_last_checked_at = self.job_seeker.last_checked_at

        employer = self.company.members.first()
        client.force_login(employer)
        # Good duration.
        hiring_start_at = today
        post_data = {
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT) if hiring_end_at else ""
        }

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        assertContains(response, LINK_RESET_MARKUP % reverse("apply:details_for_company", args=[job_application.pk]))
        assertNotContains(response, BACK_BUTTON_ARIA_LABEL)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        response = self.fill_contract_info_step(
            client, job_application, session_uuid, post_data=post_data, assert_successful=False
        )

        eligibility_url = reverse(
            "apply:eligibility",
            kwargs={"job_application_id": job_application.pk},
            query={
                "back_url": self.get_contract_info_step_url(session_uuid),
                "next_url": self.get_confirm_step_url(session_uuid),
            },
        )
        assertRedirects(response, eligibility_url, fetch_redirect_response=False)

        response = client.get(eligibility_url)
        assertContains(
            response, CONFIRM_RESET_MARKUP % reverse("apply:details_for_company", args=[job_application.pk])
        )
        assertContains(
            response,
            (
                '<button type="submit" class="btn btn-block btn-primary" aria-label="Passer à l’étape suivante">'
                "<span>Valider l’éligibilité du candidat</span>"
                "</button>"
            ),
            html=True,
        )
        assertContains(response, BACK_BUTTON_ARIA_LABEL)
        assertContains(response, self.get_contract_info_step_url(session_uuid))
        criterion1 = AdministrativeCriteria.objects.level1().order_by("?").first()
        assert not EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_company
        )
        response = client.post(eligibility_url, data={f"{criterion1.key}": "true"})
        assertRedirects(response, self.get_confirm_step_url(session_uuid), fetch_redirect_response=False)
        assert EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_company
        )

        # If you go back to contract infos, data is pre-filled
        response = client.get(self.get_contract_info_step_url(session_uuid))
        assertContains(response, f'value="{hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT)}"')

        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        self.confirm_step(client, session_uuid, reset_url=next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.hiring_start_at == hiring_start_at
        assert job_application.hiring_end_at == hiring_end_at
        assert job_application.state.is_accepted

        # test how hiring_end_date is displayed
        response = client.get(next_url)
        assertNotContains(
            response,
            users_test_constants.CERTIFIED_FORM_READONLY_HTML.format(url=get_zendesk_form_url(response.wsgi_request)),
            html=True,
        )
        # test case hiring_end_at
        if hiring_end_at:
            assertContains(
                response,
                f"<small>Fin</small><strong>{date_format(hiring_end_at, 'd F Y')}</strong>",
                html=True,
            )
        else:
            assertContains(response, '<small>Fin</small><i class="text-disabled">Non renseigné</i>', html=True)
        # last_checked_at has been updated
        assert job_application.job_seeker.last_checked_at > previous_last_checked_at

    def test_accept_with_iae_eligibility(self, client):
        today = timezone.localdate()
        job_application = self.create_job_application(
            state=JobApplicationState.PROCESSING, with_iae_eligibility_diagnosis=True
        )
        details_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})

        employer = self.company.members.first()
        client.force_login(employer)
        # Good duration.
        hiring_start_at = today
        post_data = {"hiring_end_at": ""}

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        assertContains(response, LINK_RESET_MARKUP % details_url)
        assertNotContains(response, BACK_BUTTON_ARIA_LABEL)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        self.fill_contract_info_step(client, job_application, session_uuid, post_data=post_data, reset_url=details_url)
        self.confirm_step(client, session_uuid, reset_url=details_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.hiring_start_at == hiring_start_at
        assert job_application.hiring_end_at is None
        assert job_application.state.is_accepted

    def test_accept_with_next_url(self, client):
        today = timezone.localdate()
        job_application = self.create_job_application(
            state=JobApplicationState.PROCESSING, with_iae_eligibility_diagnosis=True
        )

        employer = self.company.members.first()
        client.force_login(employer)
        # Good duration.
        hiring_start_at = today
        post_data = {"hiring_end_at": ""}

        next_url = reverse("apply:list_for_siae")
        session_uuid = self.start_accept_job_application(client, job_application, next_url=next_url)
        assert client.session[session_uuid] == {
            "job_application_id": job_application.pk,
            "reset_url": next_url,
        }
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        assertContains(response, LINK_RESET_MARKUP % next_url)
        assertNotContains(response, BACK_BUTTON_ARIA_LABEL)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        self.fill_contract_info_step(client, job_application, session_uuid, post_data=post_data, reset_url=next_url)
        self.confirm_step(client, session_uuid, reset_url=next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.hiring_start_at == hiring_start_at
        assert job_application.hiring_end_at is None
        assert job_application.state.is_accepted

    def test_nominal_geiq_case(self, client):
        today = timezone.localdate()
        job_application = self.create_job_application()
        self.company.kind = CompanyKind.GEIQ
        self.company.convention = None
        self.company.save(update_fields=["convention", "kind", "updated_at"])
        previous_last_checked_at = self.job_seeker.last_checked_at

        employer = self.company.members.first()
        client.force_login(employer)
        # Good duration.
        hiring_start_at = today

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        assertContains(response, LINK_RESET_MARKUP % reverse("apply:details_for_company", args=[job_application.pk]))
        assertNotContains(response, BACK_BUTTON_ARIA_LABEL)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        response = self.fill_contract_info_step(client, job_application, session_uuid, assert_successful=False)

        eligibility_url = reverse(
            "apply:geiq_eligibility",
            kwargs={"job_application_id": job_application.pk},
            query={
                "back_url": self.get_contract_info_step_url(session_uuid),
                "next_url": self.get_confirm_step_url(session_uuid),
            },
        )
        assertRedirects(response, eligibility_url, fetch_redirect_response=False)

        response = client.get(eligibility_url)
        assertContains(response, self.get_contract_info_step_url(session_uuid))  # cancel button
        response = client.post(eligibility_url, data={"choice": "False"})  # Skip GEIQ eligibility step
        assertContains(response, self.get_confirm_step_url(session_uuid))  # htmx response contains confirm step link
        # If you go back to contract infos, data is pre-filled
        response = client.get(self.get_contract_info_step_url(session_uuid))
        assertContains(response, f'value="{hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT)}"')

        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        self.confirm_step(client, session_uuid, reset_url=next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.hiring_start_at == hiring_start_at
        assert job_application.state.is_accepted

        # test how hiring_end_date is displayed
        response = client.get(next_url)
        assertNotContains(
            response,
            users_test_constants.CERTIFIED_FORM_READONLY_HTML.format(url=get_zendesk_form_url(response.wsgi_request)),
            html=True,
        )
        # last_checked_at has been updated
        assert job_application.job_seeker.last_checked_at > previous_last_checked_at

    @pytest.mark.usefixtures("api_particulier_settings")
    @freeze_time("2024-09-11")
    def test_select_other_job_description_for_job_application(self, client, mocker):
        criteria_kind = random.choice(list(AdministrativeCriteriaKind.certifiable_by_api_particulier()))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"],
        )
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=1)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company,
            certifiable=True,
            criteria_kinds=[criteria_kind],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=datetime.date(
                2002, 2, 20
            ),  # Required to certify the criteria later.
        )

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        contract_infos_url = self.get_contract_info_step_url(session_uuid)
        assertRedirects(response, contract_infos_url, fetch_redirect_response=False)

        response = client.get(contract_infos_url)
        assertContains(response, self.OPEN_JOBS_TEXT)
        assertNotContains(response, self.CLOSED_JOBS_TEXT)
        assertNotContains(response, self.SPECIFY_JOB_TEXT)

        # Selecting "Autre" must enable the employer to create a new job description
        # linked to the accepted job application.
        post_data = {
            "hired_job": AcceptForm.OTHER_HIRED_JOB,
        }
        post_data = self._accept_contract_post_data(job_application=job_application, post_data=post_data)
        response = client.post(contract_infos_url, data=post_data)
        assertContains(response, "Localisation du poste")
        assertContains(response, self.SPECIFY_JOB_TEXT)

        city = City.objects.order_by("?").first()
        appellation = Appellation.objects.get(rome_id="M1805")
        post_data |= {"location": city.pk, "appellation": appellation.pk}
        response = client.post(contract_infos_url, data=post_data)
        assertRedirects(response, self.get_confirm_step_url(session_uuid), fetch_redirect_response=False)
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )
        mocked_request.assert_called_once()

        # Perform some checks on job description now attached to job application
        job_application.refresh_from_db()
        assert job_application.hired_job
        assert job_application.hired_job.creation_source == JobDescriptionSource.HIRING
        assert not job_application.hired_job.is_active
        assert job_application.hired_job.description == "La structure n’a pas encore renseigné cette rubrique"

    def test_select_job_description_for_job_application(self, client, snapshot):
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)
        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        contract_infos_url = self.get_contract_info_step_url(session_uuid)
        assertRedirects(response, contract_infos_url, fetch_redirect_response=False)

        # Check optgroup labels
        job_description = JobDescriptionFactory(company=job_application.to_company, is_active=True)
        response = client.get(contract_infos_url)
        assertContains(response, f"{job_description.display_name} - {job_description.display_location}", html=True)
        assertContains(response, self.OPEN_JOBS_TEXT)
        assertNotContains(response, self.CLOSED_JOBS_TEXT)
        assertNotContains(response, self.SPECIFY_JOB_TEXT)

        # Inactive job description must also appear in select
        job_description = JobDescriptionFactory(company=job_application.to_company, is_active=False)
        with assertSnapshotQueries(snapshot(name="accept view SQL queries")):
            response = client.get(contract_infos_url)
        assertContains(response, f"{job_description.display_name} - {job_description.display_location}", html=True)
        assertContains(response, self.OPEN_JOBS_TEXT)
        assertContains(response, self.CLOSED_JOBS_TEXT)
        assertNotContains(response, self.SPECIFY_JOB_TEXT)

    def test_no_job_description_for_job_application(self, client):
        self.company.jobs.clear()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)
        employer = self.company.members.first()
        client.force_login(employer)
        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        contract_infos_url = self.get_contract_info_step_url(session_uuid)
        assertRedirects(response, contract_infos_url, fetch_redirect_response=False)

        response = client.get(contract_infos_url)
        assertNotContains(response, self.OPEN_JOBS_TEXT)
        assertNotContains(response, self.CLOSED_JOBS_TEXT)
        assertNotContains(response, self.SPECIFY_JOB_TEXT)

    def test_wrong_dates(self, client):
        today = timezone.localdate()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)
        hiring_start_at = today
        hiring_end_at = Approval.get_default_end_date(hiring_start_at)
        # Force `hiring_start_at` in past.
        hiring_start_at = hiring_start_at - relativedelta(days=1)

        employer = self.company.members.first()
        client.force_login(employer)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        response = self.fill_contract_info_step(
            client, job_application, session_uuid, post_data=post_data, assert_successful=False
        )

        assertFormError(response.context["form_accept"], "hiring_start_at", JobApplication.ERROR_START_IN_PAST)

        # Wrong dates: end < start.
        hiring_start_at = today
        hiring_end_at = hiring_start_at - relativedelta(days=1)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        response = self.fill_contract_info_step(
            client, job_application, session_uuid, post_data=post_data, assert_successful=False
        )
        assertFormError(response.context["form_accept"], None, JobApplication.ERROR_END_IS_BEFORE_START)

    def test_accept_hiring_date_after_approval(self, client, mocker):
        # Jobseeker has an approval, but it ends after the start date of the job.
        approval = ApprovalFactory(end_at=timezone.localdate() + datetime.timedelta(days=1))
        self.job_seeker.approvals.add(approval)
        job_application = self.create_job_application(
            job_seeker=self.job_seeker,
            to_company=self.company,
            sent_by_authorized_prescriber_organisation=True,
            approval=approval,
            hiring_start_at=approval.end_at + datetime.timedelta(days=1),
        )

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        post_data = self._accept_contract_post_data(
            job_application=job_application,
            post_data={
                "hiring_start_at": job_application.hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT)
            },
        )
        response = self.fill_contract_info_step(
            client, job_application, session_uuid, post_data=post_data, assert_successful=False
        )
        assertFormError(
            response.context["form_accept"],
            "hiring_start_at",
            JobApplication.ERROR_HIRES_AFTER_APPROVAL_EXPIRES,
        )

        # employer amends the situation by submitting a different hiring start date
        post_data["hiring_start_at"] = timezone.localdate().strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT)
        self.fill_contract_info_step(
            client, job_application, session_uuid, post_data=post_data, assert_successful=True
        )
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        self.confirm_step(client, session_uuid, reset_url=next_url)

    def test_no_address(self, client):
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)
        employer = self.company.members.first()
        client.force_login(employer)

        # Remove job seeker address to force address form presence
        self.job_seeker.address_line_1 = ""
        self.job_seeker.city = ""
        self.job_seeker.post_code = ""
        self.job_seeker.save(update_fields=["address_line_1", "city", "post_code"])
        # And add birth info since it is not the purpose of this test
        self.job_seeker.jobseeker_profile.birth_country = (
            Country.objects.exclude(pk=Country.FRANCE_ID).order_by("?").first()
        )
        self.job_seeker.jobseeker_profile.birthdate = datetime.date(1990, 1, 1)
        self.job_seeker.jobseeker_profile.save(update_fields=["birth_country", "birthdate"])

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        post_data = {
            "ban_api_resolved_address": "",
            "address_line_1": "",
            "post_code": "",
            "insee_code": "",
            "city": "",
            "geocoding_score": "",
            "fill_mode": "ban_api",
            "address_for_autocomplete": "",
        }

        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertFormError(response.context["form_user_address"], "address_for_autocomplete", "Ce champ est obligatoire.")

        # Trying to skip to contract step must redirect back to job seeker info step
        response = client.get(self.get_contract_info_step_url(session_uuid))
        assertRedirects(response, self.get_job_seeker_info_step_url(session_uuid), fetch_redirect_response=False)
        assertMessages(
            response,
            [messages.Message(messages.ERROR, "Certaines informations sont manquantes ou invalides")],
        )

        post_data = {
            "birthdate": self.job_seeker.jobseeker_profile.birthdate.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "birth_place": "",
            "birth_country": self.job_seeker.jobseeker_profile.birth_country.pk,
            "address_line_1": "37 B Rue du Général De Gaulle",
            "address_line_2": "",
            "post_code": "67118",
            "city": "Geispolsheim",
            "fill_mode": "ban_api",
            "insee_code": "67152",
            "ban_api_resolved_address": "37 B Rue du Général De Gaulle, 67118 Geispolsheim",
            "address_for_autocomplete": "67152_1234_00037",
        }
        response = client.post(self.get_job_seeker_info_step_url(session_uuid), data=post_data)
        assertRedirects(response, reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid}))
        self.fill_contract_info_step(client, job_application, session_uuid)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        self.confirm_step(client, session_uuid, reset_url=next_url)
        self.job_seeker.refresh_from_db()
        assert self.job_seeker.address_line_1 == "37 B Rue du Général De Gaulle"

    def test_no_diagnosis_on_job_application(self, client):
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=False)
        self.job_seeker.eligibility_diagnoses.add(diagnosis)
        # No eligibility diagnosis -> if job_seeker has a valid eligibility diagnosis, it's OK
        assert job_application.eligibility_diagnosis is None

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        self.fill_contract_info_step(client, job_application, session_uuid, assert_successful=True, post_data={})
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        self.confirm_step(client, session_uuid, reset_url=next_url)

    def test_with_active_suspension(self, client):
        """Test the `accept` transition with active suspension for active user"""
        employer = self.company.members.first()
        today = timezone.localdate()
        # Old job application of job seeker
        old_job_application = self.create_job_application(
            with_iae_eligibility_diagnosis=True, with_approval=True, hiring_start_at=today - relativedelta(days=100)
        )
        job_seeker = old_job_application.job_seeker
        # Create suspension for the job seeker
        approval = old_job_application.approval
        susension_start_at = today
        suspension_end_at = today + relativedelta(days=50)

        SuspensionFactory(
            approval=approval,
            start_at=susension_start_at,
            end_at=suspension_end_at,
            created_by=employer,
            reason=Suspension.Reason.BROKEN_CONTRACT.value,
        )

        # Now, another company wants to hire the job seeker
        other_company = CompanyFactory(with_membership=True, with_jobs=True, subject_to_iae_rules=True)
        job_application = JobApplicationFactory(
            approval=approval,
            state=job_applications_enums.JobApplicationState.PROCESSING,
            job_seeker=job_seeker,
            to_company=other_company,
            selected_jobs=other_company.jobs.all(),
        )
        other_employer = job_application.to_company.members.first()

        # login with other company
        client.force_login(other_employer)
        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        hiring_start_at = today + relativedelta(days=20)

        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        self.fill_contract_info_step(client, job_application, session_uuid, post_data=post_data)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        self.confirm_step(client, session_uuid, reset_url=next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        suspension = job_application.approval.suspension_set.in_progress().last()

        # The end date of suspension is set to d-1 of hiring start day.
        assert suspension.end_at == job_application.hiring_start_at - relativedelta(days=1)
        # Check if the duration of approval was updated correctly.
        assert job_application.approval.end_at == approval.end_at + relativedelta(
            days=(suspension.end_at - suspension.start_at).days
        )

    def test_with_manual_approval_delivery(self, client):
        """
        Test the "manual approval delivery mode" path of the view.
        """

        jobseeker_profile = self.job_seeker.jobseeker_profile
        # The state of the 3 `pole_emploi_*` fields will trigger a manual delivery.
        jobseeker_profile.nir = ""
        jobseeker_profile.pole_emploi_id = ""
        jobseeker_profile.lack_of_pole_emploi_id_reason = LackOfPoleEmploiId.REASON_FORGOTTEN
        jobseeker_profile.birth_country = Country.objects.exclude(pk=Country.FRANCE_ID).order_by("?").first()
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)

        post_data = {
            # Data for `JobSeekerPersonalDataForm`.
            "pole_emploi_id": job_application.job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": jobseeker_profile.lack_of_pole_emploi_id_reason,
            "lack_of_nir": True,
            "lack_of_nir_reason": LackOfNIRReason.NO_NIR,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        self.fill_contract_info_step(client, job_application, session_uuid)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        self.confirm_step(client, session_uuid, reset_url=next_url)
        job_application.refresh_from_db()
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_MANUAL

    def test_update_hiring_start_date_of_two_job_applications(self, client):
        hiring_start_at = timezone.localdate() + relativedelta(months=2)
        hiring_end_at = hiring_start_at + relativedelta(months=2)
        approval_default_ending = Approval.get_default_end_date(start_at=hiring_start_at)
        # Send 3 job applications to 3 different structures
        job_application = self.create_job_application(
            hiring_start_at=hiring_start_at, hiring_end_at=hiring_end_at, with_iae_eligibility_diagnosis=True
        )
        job_seeker = job_application.job_seeker

        wall_e = CompanyFactory(with_membership=True, with_jobs=True, name="WALL-E", subject_to_iae_rules=True)
        job_app_starting_earlier = JobApplicationFactory(
            job_seeker=job_seeker,
            state=job_applications_enums.JobApplicationState.PROCESSING,
            to_company=wall_e,
            selected_jobs=wall_e.jobs.all(),
        )
        vice_versa = CompanyFactory(with_membership=True, with_jobs=True, name="Vice-versa", subject_to_iae_rules=True)
        job_app_starting_later = JobApplicationFactory(
            job_seeker=job_seeker,
            state=job_applications_enums.JobApplicationState.PROCESSING,
            to_company=vice_versa,
            selected_jobs=vice_versa.jobs.all(),
        )

        # company 1 logs in and accepts the first job application.
        # The delivered approval should start at the same time as the contract.
        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        self.fill_contract_info_step(
            client, job_application, session_uuid, post_data=post_data, with_previous_step=True
        )
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )

        # First job application has been accepted.
        # All other job applications are obsolete.
        job_application.refresh_from_db()
        assert job_application.state.is_accepted
        assert job_application.approval.start_at == job_application.hiring_start_at
        assert job_application.approval.end_at == approval_default_ending
        client.logout()

        # company 2 accepts the second job application
        # but its contract starts earlier than the approval delivered the first time.
        # Approval's starting date should be brought forward.
        employer = wall_e.members.first()
        hiring_start_at = hiring_start_at - relativedelta(months=1)
        hiring_end_at = hiring_start_at + relativedelta(months=2)
        approval_default_ending = Approval.get_default_end_date(start_at=hiring_start_at)
        job_app_starting_earlier.refresh_from_db()
        assert job_app_starting_earlier.state.is_obsolete

        client.force_login(employer)
        session_uuid = self.start_accept_job_application(client, job_app_starting_earlier)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        self.fill_contract_info_step(
            client, job_app_starting_earlier, session_uuid, post_data=post_data, with_previous_step=False
        )
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_app_starting_earlier.pk}),
        )
        job_app_starting_earlier.refresh_from_db()

        # Second job application has been accepted.
        # The job seeker has now two part-time jobs at the same time.
        assert job_app_starting_earlier.state.is_accepted
        assert job_app_starting_earlier.approval.start_at == job_app_starting_earlier.hiring_start_at
        assert job_app_starting_earlier.approval.end_at == approval_default_ending
        client.logout()

        # company 3 accepts the third job application.
        # Its contract starts later than the corresponding approval.
        # Approval's starting date should not be updated.
        employer = vice_versa.members.first()
        hiring_start_at = hiring_start_at + relativedelta(months=5)
        hiring_end_at = hiring_start_at + relativedelta(months=2)
        job_app_starting_later.refresh_from_db()
        assert job_app_starting_later.state.is_obsolete

        client.force_login(employer)
        session_uuid = self.start_accept_job_application(client, job_app_starting_later)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        self.fill_contract_info_step(
            client, job_app_starting_later, session_uuid, post_data=post_data, with_previous_step=False
        )
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_app_starting_later.pk}),
        )
        job_app_starting_later.refresh_from_db()

        # Third job application has been accepted.
        # The job seeker has now three part-time jobs at the same time.
        assert job_app_starting_later.state.is_accepted
        assert job_app_starting_later.approval.start_at == job_app_starting_earlier.hiring_start_at

    def test_nir_readonly(self, client):
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)
        session_uuid = self.start_accept_job_application(client, job_application)
        jobseeker_info_url = self.get_job_seeker_info_step_url(session_uuid)
        response = client.get(jobseeker_info_url)
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        # Check that the NIR field has been removed
        assertNotContains(response, NIR_FIELD_ID)

        job_application.job_seeker.last_login = None
        job_application.job_seeker.created_by = PrescriberFactory()
        job_application.job_seeker.save()
        response = client.get(jobseeker_info_url)
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        # Check that the NIR field has been removed
        assertNotContains(response, NIR_FIELD_ID)

    def test_no_nir_update(self, client):
        jobseeker_profile = self.job_seeker.jobseeker_profile
        jobseeker_profile.nir = ""
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)
        session_uuid = self.start_accept_job_application(client, job_application)
        jobseeker_info_url = self.get_job_seeker_info_step_url(session_uuid)
        response = client.get(jobseeker_info_url)
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        # Check that the NIR field is present
        assertContains(response, NIR_FIELD_ID)

        post_data = self._accept_jobseeker_post_data(job_application)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)

        post_data["nir"] = "1234"
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        assertFormError(
            response.context["form_personal_data"],
            "nir",
            "Le numéro de sécurité sociale est trop court (15 caractères autorisés).",
        )

        NEW_NIR = "197013625838386"
        post_data["nir"] = NEW_NIR
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.nir != NEW_NIR  # Not saved yet

        self.fill_contract_info_step(client, job_application, session_uuid)
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.nir == NEW_NIR

    def test_no_nir_other_user(self, client):
        jobseeker_profile = self.job_seeker.jobseeker_profile
        jobseeker_profile.nir = ""
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)
        other_job_seeker = JobSeekerFactory(
            jobseeker_profile__with_pole_emploi_id=True,
            with_ban_api_mocked_address=True,
        )

        employer = self.company.members.first()
        client.force_login(employer)
        session_uuid = self.start_accept_job_application(client, job_application)
        jobseeker_info_url = self.get_job_seeker_info_step_url(session_uuid)
        response = client.get(jobseeker_info_url)
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)

        post_data = {
            "pole_emploi_id": jobseeker_profile.pole_emploi_id,
            "nir": other_job_seeker.jobseeker_profile.nir,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(response, "Le numéro de sécurité sociale est déjà associé à un autre utilisateur", html=True)
        assertFormError(
            response.context["form_personal_data"],
            None,
            "Ce numéro de sécurité sociale est déjà associé à un autre utilisateur.",
        )

    def test_no_nir_update_with_reason(self, client):
        jobseeker_profile = self.job_seeker.jobseeker_profile
        jobseeker_profile.nir = ""
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        jobseeker_info_url = self.get_job_seeker_info_step_url(session_uuid)
        response = client.get(jobseeker_info_url)
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)

        post_data = self._accept_jobseeker_post_data(job_application=job_application)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)

        # Check the box
        post_data["lack_of_nir"] = True
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        assertContains(response, "Veuillez sélectionner un motif pour continuer", html=True)

        post_data["lack_of_nir_reason"] = LackOfNIRReason.NO_NIR
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        job_application.job_seeker.jobseeker_profile.refresh_from_db()
        assert (
            job_application.job_seeker.jobseeker_profile.lack_of_nir_reason != LackOfNIRReason.NO_NIR
        )  # Not saved yet

        self.fill_contract_info_step(client, job_application, session_uuid)
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )
        job_application.job_seeker.jobseeker_profile.refresh_from_db()
        assert job_application.job_seeker.jobseeker_profile.lack_of_nir_reason == LackOfNIRReason.NO_NIR

    def test_lack_of_nir_reason_update(self, client):
        jobseeker_profile = self.job_seeker.jobseeker_profile
        jobseeker_profile.nir = ""
        jobseeker_profile.lack_of_nir_reason = LackOfNIRReason.NO_NIR
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        jobseeker_info_url = self.get_job_seeker_info_step_url(session_uuid)
        response = client.get(jobseeker_info_url)
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)

        # Check that the NIR field is initially disabled
        # since the job seeker has a lack_of_nir_reason
        assert response.context["form_personal_data"].fields["nir"].disabled
        NEW_NIR = "197013625838386"

        post_data = {
            "nir": NEW_NIR,
            "lack_of_nir_reason": jobseeker_profile.lack_of_nir_reason,
            "birth_country": Country.objects.exclude(pk=Country.FRANCE_ID).order_by("?").first().pk,
        }
        post_data = self._accept_jobseeker_post_data(job_application=job_application, post_data=post_data)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        job_application.job_seeker.refresh_from_db()
        # No change yet
        assert job_application.job_seeker.jobseeker_profile.lack_of_nir_reason
        assert job_application.job_seeker.jobseeker_profile.nir != NEW_NIR

        self.fill_contract_info_step(client, job_application, session_uuid)
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )
        job_application.job_seeker.refresh_from_db()
        # New NIR is set and the lack_of_nir_reason is cleaned
        assert not job_application.job_seeker.jobseeker_profile.lack_of_nir_reason
        assert job_application.job_seeker.jobseeker_profile.nir == NEW_NIR

    def test_lack_of_nir_reason_other_user(self, client):
        jobseeker_profile = self.job_seeker.jobseeker_profile
        jobseeker_profile.nir = ""
        jobseeker_profile.lack_of_nir_reason = LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        jobseeker_info_url = self.get_job_seeker_info_step_url(session_uuid)
        response = client.get(jobseeker_info_url)
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        # Check that the NIR field is initially disabled
        # since the job seeker has a lack_of_nir_reason
        assert response.context["form_personal_data"].fields["nir"].disabled

        # Check that the NIR modification link is there
        assertContains(
            response,
            (
                '<a href="'
                f'{
                    reverse(
                        "job_seekers_views:nir_modification_request",
                        kwargs={"public_id": job_application.job_seeker.public_id},
                        query={"back_url": jobseeker_info_url},
                    )
                }">Demander la correction du numéro de sécurité sociale</a>'
            ),
            html=True,
        )

    def test_accept_after_cancel(self, client):
        # A canceled job application is not linked to an approval
        # unless the job seeker has an accepted job application.
        job_application = self.create_job_application(
            state=job_applications_enums.JobApplicationState.CANCELLED, with_iae_eligibility_diagnosis=True
        )

        employer = self.company.members.first()
        client.force_login(employer)
        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        self.fill_contract_info_step(client, job_application, session_uuid)
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )

        job_application.refresh_from_db()
        assert job_application.job_seeker.approvals.count() == 1
        approval = job_application.job_seeker.approvals.first()
        assert approval.start_at == job_application.hiring_start_at
        assert job_application.state.is_accepted

    @pytest.mark.usefixtures("api_particulier_settings")
    @pytest.mark.parametrize("from_kind", {UserKind.EMPLOYER, UserKind.PRESCRIBER})
    @freeze_time("2024-09-11")
    def test_accept_iae_criteria_can_be_certified(self, client, mocker, from_kind):
        criteria_kind = random.choice(list(AdministrativeCriteriaKind.certifiable_by_api_particulier()))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"],
        )
        ######### Case 1: if CRITERIA_KIND is one of the diagnosis criteria,
        ######### birth place and birth country are required.
        birthdate = datetime.date(1995, 12, 27)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company if from_kind is UserKind.EMPLOYER else None,
            certifiable=True,
            **{f"from_{from_kind}": True},
            criteria_kinds=[criteria_kind, AdministrativeCriteriaKind.CAP_BEP],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=birthdate,
        )
        to_be_certified_criteria = diagnosis.selected_administrative_criteria.filter(
            administrative_criteria__kind__in=criteria_kind
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        assertContains(response, self.BIRTH_COUNTRY_LABEL)
        assertContains(response, self.BIRTH_PLACE_LABEL)

        # CertifiedCriteriaForm
        # Birth country is mandatory.
        post_data = {
            "birth_country": "",
            "birth_place": "",
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertFormError(response.context["form_birth_data"], "birth_country", "Le pays de naissance est obligatoire.")

        # Wrong birth country and birth place.
        post_data["birth_country"] = "0012345"
        post_data["birth_place"] = "008765"
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assert response.context["form_birth_data"].errors == {
            "birth_place": ["Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles."],
            "birth_country": [
                "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
                "Le pays de naissance est obligatoire.",
            ],
        }

        birth_country = Country.objects.get(pk=Country.FRANCE_ID)
        birth_place = Commune.objects.by_insee_code_and_period(
            "07141", job_application.job_seeker.jobseeker_profile.birthdate
        )
        # Field is disabled with Javascript on birth country input.
        # Elements with the disabled attribute are not submitted thus are not part of POST data.
        # See https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#constructing-the-form-data-set
        post_data = {
            "birthdate": birthdate.isoformat(),
            "birth_country": "",
            "birth_place": birth_place.pk,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        jobseeker_profile = job_application.job_seeker.jobseeker_profile
        jobseeker_profile.refresh_from_db()
        # Not saved yet
        assert jobseeker_profile.birth_country != birth_country
        assert jobseeker_profile.birth_place != birth_place

        self.fill_contract_info_step(client, job_application, session_uuid, assert_successful=True)
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )
        mocked_request.assert_called_once()
        jobseeker_profile = job_application.job_seeker.jobseeker_profile
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.birth_country == birth_country
        assert jobseeker_profile.birth_place == birth_place

        # certification
        for criterion in to_be_certified_criteria:
            criterion.refresh_from_db()
            assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"]
            assert criterion.certification_period == InclusiveDateRange(datetime.date(2024, 8, 1))
            assert criterion.certified_at

    @pytest.mark.usefixtures("api_particulier_settings")
    @pytest.mark.parametrize("from_kind", {UserKind.EMPLOYER, UserKind.PRESCRIBER})
    @freeze_time("2024-09-11")
    def test_accept_iae_criteria_can_be_certified_no_missing_data(self, client, mocker, from_kind):
        criteria_kind = random.choice(list(AdministrativeCriteriaKind.certifiable_by_api_particulier()))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"],
        )
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company if from_kind is UserKind.EMPLOYER else None,
            certifiable=True,
            **{f"from_{from_kind}": True},
            criteria_kinds=[criteria_kind, AdministrativeCriteriaKind.CAP_BEP],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
        )
        birthdate = datetime.date(1995, 12, 27)
        job_application.job_seeker.jobseeker_profile.birthdate = birthdate
        job_application.job_seeker.jobseeker_profile.birth_country = Country.objects.get(pk=Country.FRANCE_ID)
        job_application.job_seeker.jobseeker_profile.birth_place = Commune.objects.by_insee_code_and_period(
            "07141", job_application.job_seeker.jobseeker_profile.birthdate
        )
        job_application.job_seeker.jobseeker_profile.save(update_fields=["birthdate", "birth_country", "birth_place"])
        to_be_certified_criteria = diagnosis.selected_administrative_criteria.filter(
            administrative_criteria__kind__in=criteria_kind
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        self.fill_contract_info_step(
            client, job_application, session_uuid, assert_successful=True, with_previous_step=False
        )
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )
        mocked_request.assert_called_once()

        # certification
        for criterion in to_be_certified_criteria:
            criterion.refresh_from_db()
            assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"]
            assert criterion.certification_period == InclusiveDateRange(datetime.date(2024, 8, 1))
            assert criterion.certified_at

    @pytest.mark.usefixtures("api_particulier_settings")
    @pytest.mark.parametrize("from_kind", {UserKind.EMPLOYER, UserKind.PRESCRIBER})
    @freeze_time("2024-09-11")
    def test_accept_geiq_criteria_can_be_certified_no_missing_data(self, client, mocker, from_kind):
        criteria_kind = random.choice(list(AdministrativeCriteriaKind.certifiable_by_api_particulier()))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"],
        )
        self.company.kind = CompanyKind.GEIQ
        self.company.save()
        diagnosis = GEIQEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_geiq=self.company if from_kind is UserKind.EMPLOYER else None,
            certifiable=True,
            **{f"from_{from_kind}": True},
            criteria_kinds=[criteria_kind],
        )
        job_application = self.create_job_application(
            geiq_eligibility_diagnosis=diagnosis,
        )
        birthdate = datetime.date(1995, 12, 27)
        job_application.job_seeker.jobseeker_profile.birthdate = birthdate
        job_application.job_seeker.jobseeker_profile.birth_country = Country.objects.get(pk=Country.FRANCE_ID)
        job_application.job_seeker.jobseeker_profile.birth_place = Commune.objects.by_insee_code_and_period(
            "07141", job_application.job_seeker.jobseeker_profile.birthdate
        )
        job_application.job_seeker.jobseeker_profile.save(update_fields=["birthdate", "birth_country", "birth_place"])
        to_be_certified_criteria = GEIQSelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS,
            eligibility_diagnosis=job_application.geiq_eligibility_diagnosis,
        ).all()

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        self.fill_contract_info_step(
            client, job_application, session_uuid, assert_successful=True, with_previous_step=False
        )
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )
        mocked_request.assert_called_once()
        # certification
        for criterion in to_be_certified_criteria:
            criterion.refresh_from_db()
            assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"]
            assert criterion.certification_period == InclusiveDateRange(datetime.date(2024, 8, 1))
            assert criterion.certified_at

    @pytest.mark.usefixtures("api_particulier_settings")
    @pytest.mark.parametrize("from_kind", {UserKind.EMPLOYER, UserKind.PRESCRIBER})
    @freeze_time("2024-09-11")
    def test_accept_geiq_criteria_can_be_certified(self, client, mocker, from_kind):
        criteria_kind = random.choice(list(AdministrativeCriteriaKind.certifiable_by_api_particulier()))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"],
        )
        birthdate = datetime.date(1995, 12, 27)
        self.company.kind = CompanyKind.GEIQ
        self.company.save()
        diagnosis = GEIQEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_geiq=self.company if from_kind is UserKind.EMPLOYER else None,
            certifiable=True,
            **{f"from_{from_kind}": True},
            criteria_kinds=[criteria_kind],
        )
        job_application = self.create_job_application(
            geiq_eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=birthdate,
        )
        to_be_certified_criteria = GEIQSelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind__in=AdministrativeCriteriaKind.certifiable_by_api_particulier(),
            eligibility_diagnosis=job_application.geiq_eligibility_diagnosis,
        ).all()

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        assertContains(response, self.BIRTH_COUNTRY_LABEL)
        assertContains(response, self.BIRTH_PLACE_LABEL)

        # CertifiedCriteriaForm
        # Birth country is mandatory.
        post_data = {
            "birth_country": "",
            "birth_place": "",
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertFormError(response.context["form_birth_data"], "birth_country", "Le pays de naissance est obligatoire.")

        # Then set it.
        birth_country = Country.objects.get(pk=Country.FRANCE_ID)
        birth_place = Commune.objects.by_insee_code_and_period(
            "07141", job_application.job_seeker.jobseeker_profile.birthdate
        )
        post_data = {
            "birth_country": "",
            "birth_place": birth_place.pk,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        jobseeker_profile = job_application.job_seeker.jobseeker_profile
        # Not saved yet
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.birth_country != birth_country
        assert jobseeker_profile.birth_place != birth_place

        self.fill_contract_info_step(client, job_application, session_uuid, assert_successful=True)
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )
        mocked_request.assert_called_once()
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.birth_country == birth_country
        assert jobseeker_profile.birth_place == birth_place

        # certification
        for criterion in to_be_certified_criteria:
            criterion.refresh_from_db()
            assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"]
            assert criterion.certification_period == InclusiveDateRange(datetime.date(2024, 8, 1))
            assert criterion.certified_at

    @pytest.mark.parametrize("from_kind", {UserKind.EMPLOYER, UserKind.PRESCRIBER})
    @freeze_time("2024-09-11")
    def test_accept_not_an_siae_or_geiq_cannot_be_certified(self, client, mocker, from_kind):
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED]["json"],
        )
        # No eligibility diagnosis for other company kinds.
        kind = random.choice([x for x in CompanyKind if x not in [*CompanyKind.siae_kinds(), CompanyKind.GEIQ]])
        company = CompanyFactory(kind=kind, with_membership=True, with_jobs=True)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company if from_kind is UserKind.EMPLOYER else None,
            certifiable=True,
            **{f"from_{from_kind}": True},
            criteria_kinds=[AdministrativeCriteriaKind.RSA],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            selected_jobs=company.jobs.all(),
            to_company=company,
        )

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        assertContains(response, self.BIRTH_COUNTRY_LABEL)
        assertContains(response, self.BIRTH_PLACE_LABEL)

        birth_place = Commune.objects.by_insee_code_and_period(
            "07141", job_application.job_seeker.jobseeker_profile.birthdate
        )
        post_data = {
            "birth_country": "",
            "birth_place": birth_place.pk,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        post_data = self._accept_contract_post_data(job_application=job_application)
        self.fill_contract_info_step(
            client,
            job_application,
            session_uuid,
            post_data=post_data,
            assert_successful=True,
            with_previous_step=True,
        )
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )

        jobseeker_profile = job_application.job_seeker.jobseeker_profile
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.birth_country_id == Country.FRANCE_ID
        assert jobseeker_profile.birth_place_id == birth_place.id

    def test_accept_with_job_seeker_update(self, client):
        diagnosis = IAEEligibilityDiagnosisFactory(job_seeker=self.job_seeker, from_prescriber=True)
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=datetime.date(1995, 12, 27),
        )
        job_seeker = job_application.job_seeker
        # Remove birthdate to have the form available
        job_seeker.jobseeker_profile.birthdate = None
        job_seeker.jobseeker_profile.save(update_fields=["birthdate"])
        IdentityCertification.objects.create(
            jobseeker_profile=job_seeker.jobseeker_profile,
            certifier=IdentityCertificationAuthorities.API_PARTICULIER,
        )
        birth_country = Country.objects.get(name="BORA-BORA")

        employer = job_application.to_company.members.get()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)

        post_data = {
            "ban_api_resolved_address": job_seeker.geocoding_address,
            "address_line_1": job_seeker.address_line_1,
            "post_code": job_seeker.insee_city.post_codes[0],
            "insee_code": job_seeker.insee_city.code_insee,
            "city": job_seeker.insee_city.name,
            "fill_mode": "ban_api",
            # Select the first and only one option
            "address_for_autocomplete": "0",
            "geocoding_score": 0.9714,
            "birthdate": "",
            "birth_country": birth_country.pk,
            "pole_emploi_id": job_seeker.jobseeker_profile.pole_emploi_id,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assert response.status_code == 200
        soup = parse_response_to_soup(response, selector="#id_birth_country")
        assert soup.attrs.get("disabled", False) is False
        [selected_option] = soup.find_all(attrs={"selected": True})
        assert selected_option.text == "BORA-BORA"

    @freeze_time("2024-09-11")
    def test_accept_updated_birthdate_invalidating_birth_place(self, client, mocker):
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED]["json"],
        )
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company,
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.RSA],
        )
        # tests for a rare case where the birthdate will be cleaned for sharing between forms during the accept process
        job_application = self.create_job_application(eligibility_diagnosis=diagnosis)
        # Remove birth related infos to have the forms available
        birthdate = self.job_seeker.jobseeker_profile.birthdate
        self.job_seeker.jobseeker_profile.birthdate = None
        self.job_seeker.jobseeker_profile.birth_place = None
        self.job_seeker.jobseeker_profile.birth_country = None
        self.job_seeker.jobseeker_profile.save(update_fields=["birthdate", "birth_place", "birth_country"])

        # required assumptions for the test case
        assert self.company.is_subject_to_iae_rules
        ed = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=self.job_seeker, for_siae=self.company)
        assert ed and ed.criteria_can_be_certified()

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)

        birth_place = (
            Commune.objects.filter(
                # The birthdate must be >= 1900-01-01, and we’re removing 1 day from start_date.
                Q(start_date__gt=datetime.date(1900, 1, 1)),
                # Must be a valid choice for the user current birthdate.
                Q(start_date__lte=birthdate),
                Q(end_date__gte=birthdate) | Q(end_date=None),
            )
            .exclude(
                Exists(
                    # The same code must not exists at the early_date.
                    Commune.objects.exclude(pk=OuterRef("pk")).filter(
                        code=OuterRef("code"),
                        start_date__lt=OuterRef("start_date"),
                    )
                )
            )
            .first()
        )
        early_date = birth_place.start_date - datetime.timedelta(days=1)
        post_data = {
            "birth_place": birth_place.pk,
            "birthdate": early_date,  # invalidates birth_place lookup, triggering error
        }

        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        expected_msg = (
            f"Le code INSEE {birth_place.code} n'est pas référencé par l'ASP en date du {early_date:%d/%m/%Y}"
        )

        assert response.context["form_birth_data"].errors == {
            "birth_place": [expected_msg],
        }

        # assert malformed birthdate does not crash view
        post_data["birthdate"] = "20240-001-001"
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assert response.context["form_birth_data"].errors == {"birthdate": ["Saisissez une date valide."]}

        # test that fixing the birthdate fixes the form submission
        post_data["birthdate"] = birth_place.start_date + datetime.timedelta(days=1)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        self.fill_contract_info_step(client, job_application, session_uuid, assert_successful=True)
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )

    @freeze_time("2024-09-11")
    def test_accept_born_in_france_no_birth_place(self, client, mocker):
        birthdate = datetime.date(1995, 12, 27)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company,
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.RSA],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=birthdate,
        )
        client.force_login(job_application.to_company.members.get())
        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)

        post_data = self._accept_jobseeker_post_data(job_application=job_application)
        post_data["birth_country"] = Country.FRANCE_ID
        post_data["birth_place"] = ""
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                <p>
                    <strong>Votre formulaire contient une erreur</strong>
                </p>
                <ul class="mb-0">
                    <li>
                        La commune de naissance doit être spécifiée si et seulement si le pays de naissance
                        est la France.
                    </li>
                </ul>
            </div>""",
            html=True,
            count=1,
        )

    @freeze_time("2024-09-11")
    def test_accept_born_outside_of_france_specifies_birth_place(self, client, mocker):
        birthdate = datetime.date(1995, 12, 27)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company,
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.RSA],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=birthdate,
        )
        client.force_login(job_application.to_company.members.get())

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        post_data = self._accept_jobseeker_post_data(job_application=job_application)
        post_data["birth_country"] = Country.objects.order_by("?").exclude(group=Country.Group.FRANCE).first().pk
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                <p>
                    <strong>Votre formulaire contient une erreur</strong>
                </p>
                <ul class="mb-0">
                    <li>
                        La commune de naissance doit être spécifiée si et seulement si le pays de naissance
                        est la France.
                    </li>
                </ul>
            </div>""",
            html=True,
            count=1,
        )

    @freeze_time("2025-06-06")
    def test_identity_certified_by_api_particulier_birth_fields_not_readonly_if_empty(self, client):
        birth_place = Commune.objects.by_insee_code_and_period("07141", datetime.date(1990, 1, 1))

        job_seeker = JobSeekerFactory(
            jobseeker_profile__with_pole_emploi_id=True,
            with_ban_api_mocked_address=True,
            jobseeker_profile__birth_place=None,
            jobseeker_profile__birth_country=None,
        )
        selected_criteria = IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__job_seeker=job_seeker,
            eligibility_diagnosis__author_siae=self.company,
            criteria_certified=True,
            certifiable_by_api_particulier=True,
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            to_company=self.company,
            state=JobApplicationState.PROCESSING,
            eligibility_diagnosis=selected_criteria.eligibility_diagnosis,
            selected_jobs=[self.company.jobs.first()],
        )
        client.force_login(self.company.members.get())

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        form = response.context["form_birth_data"]
        assert form.fields["birth_place"].disabled is False
        assert form.fields["birth_country"].disabled is False
        post_data = {
            "title": job_seeker.title,
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "birth_place": birth_place.pk,
            "birth_country": Country.FRANCE_ID,
            "birthdate": job_seeker.jobseeker_profile.birthdate,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        # Not saved yet
        refreshed_job_seeker = User.objects.select_related("jobseeker_profile").get(pk=job_seeker.pk)
        assert refreshed_job_seeker.jobseeker_profile.birth_place_id != birth_place.pk
        assert refreshed_job_seeker.jobseeker_profile.birth_country_id != Country.FRANCE_ID

        self.fill_contract_info_step(client, job_application, session_uuid)
        self.confirm_step(
            client,
            session_uuid,
            reset_url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        )
        refreshed_job_seeker = User.objects.select_related("jobseeker_profile").get(pk=job_seeker.pk)
        assert refreshed_job_seeker.jobseeker_profile.birth_place_id == birth_place.pk
        assert refreshed_job_seeker.jobseeker_profile.birth_country_id == Country.FRANCE_ID


class TestFillJobSeekerInfosForAccept:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        self.job_seeker = JobSeekerFactory(
            first_name="Clara",
            last_name="Sion",
            jobseeker_profile__with_pole_emploi_id=True,
            with_ban_geoloc_address=True,
            born_in_france=True,
        )
        self.company = CompanyFactory(with_membership=True)
        if self.company.is_subject_to_iae_rules:
            IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        elif self.company.kind == CompanyKind.GEIQ:
            GEIQEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        # This is the city matching with_ban_geoloc_address trait
        self.city = create_city_geispolsheim()

        settings.API_GEOPF_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_first_geocoding_data,
        )

    def accept_contract(self, client, job_application, session_uuid):
        post_data = {
            "hiring_start_at": timezone.localdate().strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "answer": "",
        }
        if job_application.to_company.kind == CompanyKind.GEIQ:
            create_test_romes_and_appellations(["N1101"], appellations_per_rome=1)  # For hired_job field
            post_data.update(
                {
                    "prehiring_guidance_days": 10,
                    "contract_type": ContractType.APPRENTICESHIP,
                    "nb_hours_per_week": 10,
                    "qualification_type": QualificationType.CQP,
                    "qualification_level": QualificationLevel.LEVEL_4,
                    "planned_training_hours": 20,
                    "hired_job": JobDescriptionFactory(company=self.company).pk,
                }
            )
        response = client.post(
            reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid}),
            data=post_data,
        )
        assertRedirects(
            response,
            reverse("apply:accept_confirmation", kwargs={"session_uuid": session_uuid}),
        )
        response = client.post(reverse("apply:accept_confirmation", kwargs={"session_uuid": session_uuid}))
        assertRedirects(
            response,
            reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
            fetch_redirect_response=False,
        )

    def test_no_missing_data_iae(self, client, snapshot):
        # Ensure company is SIAE kind since it will trigger an extra query for eligibility diagnosis
        # changing the SQL queries snapshot
        if not self.company.is_subject_to_iae_rules:
            self.company.kind = random.choice(list(CompanyKind.siae_kinds()))
            self.company.convention = SiaeConventionFactory(kind=self.company.kind)
            self.company.save(update_fields=["convention", "kind", "updated_at"])
            IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )
        client.force_login(self.company.members.first())

        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept)
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        fill_job_seeker_infos_url = reverse(
            "apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid}
        )
        assertRedirects(
            response,
            fill_job_seeker_infos_url,
            fetch_redirect_response=False,
        )

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(fill_job_seeker_infos_url)
        assertRedirects(response, reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid}))

    @pytest.mark.parametrize("address", ["empty", "incomplete"])
    def test_no_address(self, client, address):
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )
        address_kwargs = {
            "address_line_1": "",
            "city": "",
            "post_code": "",
        }
        if address == "incomplete":
            address_kwargs.pop(random.choice(list(address_kwargs.keys())))

        # Remove job seeker address
        for key, value in address_kwargs.items():
            setattr(self.job_seeker, key, value)
        self.job_seeker.save(update_fields=address_kwargs.keys())

        client.force_login(self.company.members.first())

        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept)
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        fill_job_seeker_infos_url = reverse(
            "apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid}
        )
        assertRedirects(
            response,
            fill_job_seeker_infos_url,
            fetch_redirect_response=False,
        )

        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, "Accepter la candidature de SION Clara")

        post_data = {
            "address_line_1": "128 Rue de Grenelle",
            "address_line_2": "",
            "post_code": "67118",
            "city": "Geispolsheim",
            "fill_mode": "ban_api",
            "insee_code": "67152",
            "ban_api_resolved_address": "128 Rue de Grenelle 67118 Geispolsheim",
            "address_for_autocomplete": "67152_1234_00128",
        }
        # Test with invalid data
        response = client.post(
            fill_job_seeker_infos_url,
            data=post_data | {"address_line_1": "", "address_for_autocomplete": ""},
        )
        assert response.status_code == 200
        assertFormError(response.context["form_user_address"], "address_for_autocomplete", "Ce champ est obligatoire.")
        response = client.post(fill_job_seeker_infos_url, data=post_data)
        assertRedirects(response, reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid}))
        assert client.session[session_uuid]["job_seeker_info_forms_data"] == {
            "user_address": {
                "address_line_1": "128 Rue de Grenelle",
                "address_line_2": "",
                "post_code": "67118",
                "city": "Geispolsheim",
                "fill_mode": "ban_api",
                "insee_code": "67152",
                "ban_api_resolved_address": "128 Rue de Grenelle 67118 Geispolsheim",
                "address_for_autocomplete": "67152_1234_00128",
            },
        }
        # If you come back to the view, it is pre-filled with session data
        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, "128 Rue de Grenelle")

        # Check that address infos are saved (if modified) after filling contract info step
        self.accept_contract(client, job_application, session_uuid)
        self.job_seeker.refresh_from_db()
        assert self.job_seeker.address_line_1 == "128 Rue de Grenelle"
        assert self.job_seeker.post_code == "67118"
        assert self.job_seeker.city == "Geispolsheim"

    @pytest.mark.parametrize("birth_country", [None, "france", "other"])
    def test_no_birthdate(self, client, birth_country):
        client.force_login(self.company.members.first())
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )
        self.job_seeker.jobseeker_profile.birthdate = None
        if birth_country == "france":
            self.job_seeker.jobseeker_profile.birth_country_id = Country.FRANCE_ID
            self.job_seeker.jobseeker_profile.birth_place = Commune.objects.by_insee_code_and_period(
                "59183", datetime.date(1990, 1, 1)
            )
        elif birth_country == "other":
            self.job_seeker.jobseeker_profile.birth_country = (
                Country.objects.exclude(pk=Country.FRANCE_ID).order_by("?").first()
            )
            self.job_seeker.jobseeker_profile.birth_place = None
        else:
            self.job_seeker.jobseeker_profile.birth_country = None
            self.job_seeker.jobseeker_profile.birth_place = None
        self.job_seeker.jobseeker_profile.save(update_fields=["birthdate", "birth_country", "birth_place"])

        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept)
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        fill_job_seeker_infos_url = reverse(
            "apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid}
        )
        accept_contract_infos_url = reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid})
        assertRedirects(
            response,
            fill_job_seeker_infos_url,
            fetch_redirect_response=False,
        )

        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, "Accepter la candidature de SION Clara")
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)

        COUNTRY_FIELD_ID = 'id="id_birth_country"'
        PLACE_FIELD_ID = 'id="id_birth_place"'
        NEW_BIRTHDATE = datetime.date(1990, 1, 1)
        if birth_country == "other":
            assertNotContains(response, COUNTRY_FIELD_ID)
            assertNotContains(response, PLACE_FIELD_ID)
            invalid_post_data = {"birthdate": ""}

            def assertForm(form):
                assertFormError(form, "birthdate", "Ce champ est obligatoire.")

            valid_post_data = {"birthdate": NEW_BIRTHDATE}
            birth_place = None
        else:
            assertContains(response, COUNTRY_FIELD_ID)
            assertContains(response, PLACE_FIELD_ID)
            birth_place = (
                Commune.objects.filter(
                    # The birthdate must be >= 1900-01-01, and we’re removing 1 day from start_date.
                    Q(start_date__gt=datetime.date(1900, 1, 1)),
                    # Must be a valid choice for the user current birthdate.
                    Q(start_date__lte=NEW_BIRTHDATE),
                    Q(end_date__gte=NEW_BIRTHDATE) | Q(end_date=None),
                )
                .order_by("?")
                .first()
            )

            bad_birthdate = birth_place.start_date - datetime.timedelta(days=1)
            invalid_post_data = {
                "birthdate": bad_birthdate,
                "birth_place": birth_place.pk,
                "birth_country": Country.FRANCE_ID,
            }

            def assertForm(form):
                assertFormError(
                    form,
                    "birth_place",
                    (
                        f"Le code INSEE {birth_place.code} n'est pas référencé par l'ASP en date "
                        f"du {bad_birthdate:%d/%m/%Y}"
                    ),
                )

            valid_post_data = {
                "birthdate": NEW_BIRTHDATE,
                "birth_place": birth_place.pk,
                "birth_country": Country.FRANCE_ID,
            }

        # Test with invalid data
        response = client.post(fill_job_seeker_infos_url, data=invalid_post_data)
        assert response.status_code == 200
        assertForm(response.context["form_birth_data"])
        # Then with valid data
        response = client.post(fill_job_seeker_infos_url, data=valid_post_data)
        assertRedirects(response, accept_contract_infos_url)
        assert client.session[session_uuid]["job_seeker_info_forms_data"] == {
            "birth_data": valid_post_data,
        }
        # If you come back to the view, it is pre-filled with session data
        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, NEW_BIRTHDATE)

        # Check that birth infos are saved (if modified) after filling contract info step
        self.accept_contract(client, job_application, session_uuid)
        self.job_seeker.jobseeker_profile.refresh_from_db()
        assert self.job_seeker.jobseeker_profile.birthdate == NEW_BIRTHDATE
        assert self.job_seeker.jobseeker_profile.birth_place == birth_place
        if birth_country != "other":
            assert self.job_seeker.jobseeker_profile.birth_country_id == Country.FRANCE_ID

    @pytest.mark.parametrize("in_france", [True, False])
    def test_company_no_birth_country(self, client, in_france):
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )

        assert self.job_seeker.jobseeker_profile.birthdate
        self.job_seeker.jobseeker_profile.birth_country = None
        self.job_seeker.jobseeker_profile.birth_place = None
        self.job_seeker.jobseeker_profile.save(update_fields=["birth_country", "birth_place"])

        client.force_login(self.company.members.first())
        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept)
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        fill_job_seeker_infos_url = reverse(
            "apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid}
        )
        accept_contract_infos_url = reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid})
        assertRedirects(
            response,
            fill_job_seeker_infos_url,
            fetch_redirect_response=False,
        )

        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, "Accepter la candidature de SION Clara")
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)

        if in_france:
            new_country = Country.objects.get(pk=Country.FRANCE_ID)
            new_place = (
                Commune.objects.filter(
                    # The birthdate must be >= 1900-01-01, and we’re removing 1 day from start_date.
                    Q(start_date__gt=datetime.date(1900, 1, 1)),
                    # Must be a valid choice for the user current birthdate.
                    Q(start_date__lte=self.job_seeker.jobseeker_profile.birthdate),
                    Q(end_date__gte=self.job_seeker.jobseeker_profile.birthdate) | Q(end_date=None),
                )
                .order_by("?")
                .first()
            )

            invalid_post_data = {
                "birth_place": "",
                "birth_country": Country.FRANCE_ID,
            }

            def assertForm(form):
                assertFormError(
                    form,
                    None,
                    (
                        "La commune de naissance doit être spécifiée si et seulement si le pays de naissance est "
                        "la France."
                    ),
                )

            valid_post_data = {
                "birth_place": new_place.pk,
            }
        else:
            new_country = Country.objects.exclude(pk=Country.FRANCE_ID).order_by("?").first()
            new_place = None

            invalid_post_data = {"birth_country": ""}

            def assertForm(form):
                assertFormError(form, "birth_country", "Le pays de naissance est obligatoire.")

            valid_post_data = {"birth_country": new_country.pk}

        # Test with invalid data
        response = client.post(fill_job_seeker_infos_url, data=invalid_post_data)
        assert response.status_code == 200
        assertForm(response.context["form_birth_data"])
        # Then with valid data
        response = client.post(fill_job_seeker_infos_url, data=valid_post_data)
        assertRedirects(response, accept_contract_infos_url)
        assert client.session[session_uuid]["job_seeker_info_forms_data"] == {
            "birth_data": {
                "birth_place": new_place and new_place.pk,
                "birth_country": new_country.pk,
            }
        }
        # If you come back to the view, it is pre-filled with session data
        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, f'<option value="{new_country.pk}" selected>')

        # Check that birth infos are saved (if modified) after filling contract info step
        self.accept_contract(client, job_application, session_uuid)
        self.job_seeker.jobseeker_profile.refresh_from_db()
        assert self.job_seeker.jobseeker_profile.birth_country_id == new_country.pk
        assert self.job_seeker.jobseeker_profile.birth_place == new_place

    @pytest.mark.parametrize("with_lack_of_nir_reason", [True, False])
    def test_company_no_nir(self, client, with_lack_of_nir_reason):
        client.force_login(self.company.members.first())
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )
        # Remove job seeker nir, with or without a reason
        self.job_seeker.jobseeker_profile.nir = ""
        if with_lack_of_nir_reason:
            self.job_seeker.jobseeker_profile.lack_of_nir_reason = random.choice(
                [LackOfNIRReason.NO_NIR, LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER]
            )
        else:
            self.job_seeker.jobseeker_profile.lack_of_nir_reason = ""
        self.job_seeker.jobseeker_profile.save(update_fields=["nir", "lack_of_nir_reason"])

        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept)
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        fill_job_seeker_infos_url = reverse(
            "apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid}
        )
        accept_contract_infos_url = reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid})
        assertRedirects(
            response,
            fill_job_seeker_infos_url,
            fetch_redirect_response=False,
        )

        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, "Accepter la candidature de SION Clara")
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)

        # Trying to skip to contract step must redirect back to job seeker info step if a reason is missing
        response = client.get(accept_contract_infos_url)
        if with_lack_of_nir_reason:
            # With a reason, it's OK since the form is valid
            assert response.status_code == 200
        else:
            assertRedirects(response, fill_job_seeker_infos_url, fetch_redirect_response=False)
            assertMessages(
                response,
                [messages.Message(messages.ERROR, "Certaines informations sont manquantes ou invalides")],
            )

        # Test with invalid data
        response = client.post(fill_job_seeker_infos_url, data={"nir": ""})
        assert response.status_code == 200
        assertFormError(
            response.context["form_personal_data"], "nir", "Le numéro de sécurité sociale n'est pas valide"
        )

        # Fill new nir
        NEW_NIR = "197013625838386"
        response = client.post(
            fill_job_seeker_infos_url,
            data={"nir": NEW_NIR, "lack_of_nir": False, "lack_of_nir_reason": ""},
        )
        assertRedirects(response, accept_contract_infos_url)

        assert client.session[session_uuid]["job_seeker_info_forms_data"] == {
            "personal_data": {
                "nir": NEW_NIR,
                "lack_of_nir": False,
                "lack_of_nir_reason": "",
            },
        }
        # If you come back to the view, it is pre-filled with session data
        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, NEW_NIR)

        # Check that nir is saved after filling contract info step
        self.accept_contract(client, job_application, session_uuid)
        self.job_seeker.jobseeker_profile.refresh_from_db()
        assert self.job_seeker.jobseeker_profile.nir == NEW_NIR

    @pytest.mark.parametrize("with_lack_of_pole_emploi_id_reason", [True, False])
    def test_company_no_pole_emploi_id(self, client, with_lack_of_pole_emploi_id_reason):
        POLE_EMPLOI_FIELD_MARKER = 'id="id_pole_emploi_id"'
        client.force_login(self.company.members.first())
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )
        # Remove job seeker nir, with or without a reason
        self.job_seeker.jobseeker_profile.pole_emploi_id = ""
        if with_lack_of_pole_emploi_id_reason:
            self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason = random.choice(
                [LackOfPoleEmploiId.REASON_NOT_REGISTERED, LackOfPoleEmploiId.REASON_FORGOTTEN]
            )
        else:
            self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason = ""
        self.job_seeker.jobseeker_profile.save(update_fields=["pole_emploi_id", "lack_of_pole_emploi_id_reason"])

        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept)
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        fill_job_seeker_infos_url = reverse(
            "apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid}
        )
        accept_contract_infos_url = reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid})
        assertRedirects(
            response,
            fill_job_seeker_infos_url,
            fetch_redirect_response=False,
        )

        response = client.get(fill_job_seeker_infos_url)

        NEW_POLE_EMPLOI_ID = "1234567A"
        PERSONAL_DATA_SESSION_KEY = "job_seeker_info_forms_data"
        if with_lack_of_pole_emploi_id_reason:
            assertRedirects(response, accept_contract_infos_url)
            assert PERSONAL_DATA_SESSION_KEY not in client.session[session_uuid]
        else:
            assertContains(response, "Accepter la candidature de SION Clara")
            assertContains(response, NEXT_BUTTON_MARKUP, html=True)
            # If no reason is present, the pole_emploi_id field is shown
            assertContains(response, POLE_EMPLOI_FIELD_MARKER)
            # Trying to skip to contract step must redirect back to job seeker info step if a reason is missing
            response = client.get(accept_contract_infos_url)
            assertRedirects(response, fill_job_seeker_infos_url, fetch_redirect_response=False)
            assertMessages(
                response,
                [messages.Message(messages.ERROR, "Certaines informations sont manquantes ou invalides")],
            )
            # Test with invalid data
            response = client.post(
                fill_job_seeker_infos_url, data={"pole_emploi_id": "", "lack_of_pole_emploi_id_reason": ""}
            )
            assert response.status_code == 200
            assertFormError(
                response.context["form_personal_data"],
                None,
                "Renseignez soit un identifiant France Travail, soit la raison de son absence.",
            )
            response = client.post(
                fill_job_seeker_infos_url,
                data={"pole_emploi_id": NEW_POLE_EMPLOI_ID, "lack_of_pole_emploi_id_reason": ""},
            )
            assertRedirects(response, accept_contract_infos_url)
            assert client.session[session_uuid][PERSONAL_DATA_SESSION_KEY] == {
                "personal_data": {
                    "pole_emploi_id": NEW_POLE_EMPLOI_ID,
                    "lack_of_pole_emploi_id_reason": "",
                },
            }
            # If you come back to the view, it is pre-filled with session data
            response = client.get(fill_job_seeker_infos_url)
            assertContains(response, NEW_POLE_EMPLOI_ID)

        # Check that pole_emploi_id is saved (if modified) after filling contract info step
        self.accept_contract(client, job_application, session_uuid)
        self.job_seeker.jobseeker_profile.refresh_from_db()
        if not with_lack_of_pole_emploi_id_reason:
            assert self.job_seeker.jobseeker_profile.pole_emploi_id == NEW_POLE_EMPLOI_ID
            assert self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason == ""
        else:
            assert self.job_seeker.jobseeker_profile.pole_emploi_id == ""
            assert self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason != ""


class TestAcceptConfirmation:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        self.job_seeker = JobSeekerFactory(
            first_name="Clara",
            last_name="Sion",
            jobseeker_profile__with_pole_emploi_id=True,
            with_ban_geoloc_address=True,
            born_in_france=True,
        )
        # This is the city matching with_ban_geoloc_address trait
        self.city = create_city_geispolsheim()

        settings.API_BAN_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_first_geocoding_data,
        )

    def test_as_iae(self, client, snapshot):
        hiring_start_at = timezone.localdate()
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        client.force_login(company.members.first())
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=company,
        )
        accept_session = initialize_accept_session(
            client,
            {
                "job_application_id": job_application.pk,
                "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
                "contract_form_data": {"hiring_start_at": hiring_start_at},
            },
        )
        accept_session.save()
        confirmation_url = reverse("apply:accept_confirmation", kwargs={"session_uuid": accept_session.name})

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(confirmation_url)
        assertContains(response, "Confirmer l’embauche de SION Clara")
        assertContains(response, hiring_start_at.strftime("%d/%m/%Y"))

        response = client.post(confirmation_url)
        assertRedirects(
            response, reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        )

        job_application.refresh_from_db()
        assert job_application.job_seeker == self.job_seeker
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.answer == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.hiring_start_at == hiring_start_at

        assert accept_session.name not in client.session

    def test_as_iae_missing_data(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        client.force_login(company.members.first())
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=company,
        )
        accept_session = initialize_accept_session(
            client,
            {
                "job_application_id": job_application.pk,
                "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
                "contract_form_data": {"hiring_start_at": None},
            },
        )
        accept_session.save()

        response = client.get(reverse("apply:accept_confirmation", kwargs={"session_uuid": accept_session.name}))
        assertRedirects(response, reverse("apply:accept_contract_infos", kwargs={"session_uuid": accept_session.name}))

        response = client.post(reverse("apply:accept_confirmation", kwargs={"session_uuid": accept_session.name}))
        assertRedirects(response, reverse("apply:accept_contract_infos", kwargs={"session_uuid": accept_session.name}))
        job_application.refresh_from_db()
        assert job_application.state == JobApplicationState.PROCESSING

    def test_as_geiq(self, client, snapshot):
        company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True, with_jobs=True)
        GEIQEligibilityDiagnosisFactory(job_seeker=self.job_seeker, from_prescriber=True)
        client.force_login(company.members.first())
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=company,
        )
        hiring_start_at = timezone.localdate()
        hiring_end_at = hiring_start_at + datetime.timedelta(days=30)
        accept_session = initialize_accept_session(
            client,
            {
                "selected_jobs": [],
                "job_application_id": job_application.pk,
                "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
                "contract_form_data": {
                    "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                    "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                    "answer": "OK",
                    "prehiring_guidance_days": 4,
                    "nb_hours_per_week": 5,
                    "planned_training_hours": 6,
                    "contract_type": ContractType.OTHER,
                    "contract_type_details": "Contrat spécifique pour ce test",
                    "qualification_type": QualificationType.CQP,
                    "qualification_level": QualificationLevel.LEVEL_3,
                    "hired_job": company.job_description_through.first().pk,
                },
            },
        )
        accept_session.save()
        confirmation_url = reverse("apply:accept_confirmation", kwargs={"session_uuid": accept_session.name})

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(confirmation_url)
        assertContains(response, "Confirmer l’embauche de SION Clara")
        assertContains(response, hiring_start_at.strftime("%d/%m/%Y"))
        assertContains(response, hiring_end_at.strftime("%d/%m/%Y"))

        response = client.post(confirmation_url)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url)

        job_application.refresh_from_db()
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.answer == "OK"
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.hiring_start_at == hiring_start_at
        assert job_application.hiring_end_at == hiring_end_at
        assert job_application.prehiring_guidance_days == 4
        assert job_application.nb_hours_per_week == 5
        assert job_application.planned_training_hours == 6
        assert job_application.contract_type == ContractType.OTHER
        assert job_application.contract_type_details == "Contrat spécifique pour ce test"
        assert job_application.qualification_type == QualificationType.CQP
        assert job_application.qualification_level == QualificationLevel.LEVEL_3
        assert job_application.hired_job_id == company.job_description_through.first().pk

        assert accept_session.name not in client.session

    def test_as_geiq_missing_data(self, client):
        company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True, with_jobs=True)
        GEIQEligibilityDiagnosisFactory(job_seeker=self.job_seeker, from_prescriber=True)
        client.force_login(company.members.first())
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=company,
        )
        hiring_start_at = timezone.localdate()
        hiring_end_at = hiring_start_at + datetime.timedelta(days=30)
        accept_session = initialize_accept_session(
            client,
            {
                "selected_jobs": [],
                "job_application_id": job_application.pk,
                "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
                "contract_form_data": {
                    "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                    "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                    "answer": "OK",
                    "prehiring_guidance_days": 4,
                    "nb_hours_per_week": 5,
                    "planned_training_hours": 6,
                    "contract_type": ContractType.OTHER,
                    "contract_type_details": "Contrat spécifique pour ce test",
                    "qualification_type": "",  # Missing
                    "qualification_level": QualificationLevel.LEVEL_3,
                    "hired_job": company.job_description_through.first().pk,
                },
            },
        )
        accept_session.save()
        response = client.get(reverse("apply:accept_confirmation", kwargs={"session_uuid": accept_session.name}))
        assertRedirects(response, reverse("apply:accept_contract_infos", kwargs={"session_uuid": accept_session.name}))

        response = client.post(reverse("apply:accept_confirmation", kwargs={"session_uuid": accept_session.name}))
        assertRedirects(response, reverse("apply:accept_contract_infos", kwargs={"session_uuid": accept_session.name}))
        job_application.refresh_from_db()
        assert job_application.state == JobApplicationState.PROCESSING


@pytest.mark.parametrize("qualification_type", job_applications_enums.QualificationType)
def test_reload_qualification_fields(qualification_type, client, snapshot):
    company = CompanyFactory(pk=10, kind=CompanyKind.GEIQ, with_membership=True)
    employer = company.members.first()
    client.force_login(employer)
    job_seeker = JobSeekerFactory(for_snapshot=True)
    url = reverse(
        "apply:reload_qualification_fields",
        kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
    )
    response = client.post(
        url,
        data={
            "guidance_days": "0",
            "contract_type": ContractType.APPRENTICESHIP,
            "contract_type_details": "",
            "nb_hours_per_week": "",
            "hiring_start_at": "",
            "qualification_type": qualification_type,
            "qualification_level": "",
            "planned_training_hours": "0",
            "hiring_end_at": "",
            "answer": "",
        },
    )
    assert response.text == snapshot()


@pytest.mark.parametrize("missing_field", [("company_pk", 0), ("job_seeker_public_id", str(uuid.uuid4()))])
def test_reload_qualification_fields_404(client, missing_field):
    company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
    employer = company.members.first()
    client.force_login(employer)
    job_seeker = JobSeekerFactory(for_snapshot=True)
    kwargs = {"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id}
    kwargs[missing_field[0]] = missing_field[1]
    url = reverse("apply:reload_qualification_fields", kwargs=kwargs)
    response = client.post(
        url,
        data={
            "guidance_days": "0",
            "contract_type": ContractType.APPRENTICESHIP,
            "contract_type_details": "",
            "nb_hours_per_week": "",
            "hiring_start_at": "",
            "qualification_type": job_applications_enums.QualificationType.CQP,
            "qualification_level": "",
            "planned_training_hours": "0",
            "hiring_end_at": "",
            "answer": "",
        },
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "contract_type",
    [value for value, _label in ContractType.choices_for_company_kind(CompanyKind.GEIQ)],
)
def test_reload_contract_type_and_options(contract_type, client, snapshot):
    company = CompanyFactory(pk=10, kind=CompanyKind.GEIQ, with_membership=True)
    employer = company.members.first()
    client.force_login(employer)
    job_seeker = JobSeekerFactory(for_snapshot=True)
    url = reverse(
        "apply:reload_contract_type_and_options",
        kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
    )
    response = client.post(
        url,
        data={
            "guidance_days": "0",
            "contract_type": contract_type,
            "contract_type_details": "",
            "nb_hours_per_week": "",
            "hiring_start_at": "",
            "qualification_type": "CQP",
            "qualification_level": "",
            "planned_training_hours": "0",
            "hiring_end_at": "",
            "answer": "",
        },
    )
    assert response.text == snapshot()


@pytest.mark.parametrize("missing_field", [("company_pk", 0), ("job_seeker_public_id", str(uuid.uuid4()))])
def test_reload_contract_type_and_options_404(client, missing_field):
    company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
    employer = company.members.first()
    client.force_login(employer)
    job_seeker = JobSeekerFactory(for_snapshot=True)
    kwargs = {"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id}
    kwargs[missing_field[0]] = missing_field[1]
    url = reverse("apply:reload_contract_type_and_options", kwargs=kwargs)
    response = client.post(
        url,
        data={
            "guidance_days": "0",
            "contract_type": ContractType.APPRENTICESHIP,
            "contract_type_details": "",
            "nb_hours_per_week": "",
            "hiring_start_at": "",
            "qualification_type": "CQP",
            "qualification_level": "",
            "planned_training_hours": "0",
            "hiring_end_at": "",
            "answer": "",
        },
    )
    assert response.status_code == 404


def test_htmx_reload_contract_type_and_options_in_wizard(client):
    job_application = JobApplicationFactory(
        to_company__kind=CompanyKind.GEIQ,
        state=job_applications_enums.JobApplicationState.PROCESSING,
        job_seeker__for_snapshot=True,
        job_seeker__with_address=True,
        job_seeker__jobseeker_profile__with_pole_emploi_id=True,
        job_seeker__born_in_france=True,  # To avoid job seeker infos step
    )
    employer = job_application.to_company.members.first()
    client.force_login(employer)
    accept_session = initialize_accept_session(
        client,
        {
            "job_application_id": job_application.pk,
            "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        },
    )
    accept_session.save()
    contract_url = reverse("apply:accept_contract_infos", kwargs={"session_uuid": accept_session.name})
    data = {
        "guidance_days": "1",
        "contract_type": ContractType.PROFESSIONAL_TRAINING,
        "contract_type_details": "",
        "nb_hours_per_week": "2",
        "hiring_start_at": "",  # No date to ensure error
        "qualification_type": "CQP",
        "qualification_level": job_applications_enums.QualificationLevel.LEVEL_3,
        "prehiring_guidance_days": "0",
        "planned_training_hours": "0",
        "hiring_end_at": "",
        "answer": "",
    }
    response = client.post(contract_url, data=data)
    form_soup = parse_response_to_soup(response, selector=".c-form > form")

    # Update form soup with htmx call
    reload_url = reverse(
        "apply:reload_contract_type_and_options",
        kwargs={
            "company_pk": job_application.to_company.pk,
            "job_seeker_public_id": job_application.job_seeker.public_id,
        },
    )
    data["contract_type"] = ContractType.PERMANENT
    htmx_response = client.post(
        reload_url,
        data=data,
    )
    update_page_with_htmx(form_soup, "#id_contract_type", htmx_response)

    # Check that a complete re-POST returns the exact same form
    response = client.post(contract_url, data=data)
    reloaded_form_soup = parse_response_to_soup(response, selector=".c-form > form")
    assertSoupEqual(form_soup, reloaded_form_soup)
