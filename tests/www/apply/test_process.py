import random
from itertools import product

import pytest
from dateutil.relativedelta import relativedelta
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects, assertTemplateUsed

from itou.approvals.models import Approval, Suspension
from itou.cities.models import City
from itou.companies.enums import CompanyKind, ContractType, JobDescriptionSource
from itou.eligibility.enums import AuthorKind
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.employee_record.enums import Status
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.jobs.models import Appellation
from itou.siae_evaluations.models import Sanctions
from itou.users.enums import LackOfNIRReason, LackOfPoleEmploiId, UserKind
from itou.utils.models import InclusiveDateRange
from itou.utils.templatetags.format_filters import format_nir
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.apply.forms import AcceptForm
from tests.approvals.factories import PoleEmploiApprovalFactory, SuspensionFactory
from tests.cities.factories import create_test_cities
from tests.companies.factories import JobDescriptionFactory, SiaeFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory, GEIQEligibilityDiagnosisFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberOrganizationFactory,
    PriorActionFactory,
)
from tests.jobs.factories import create_test_romes_and_appellations
from tests.siae_evaluations.factories import EvaluatedSiaeFactory
from tests.users.factories import JobSeekerFactory, JobSeekerWithAddressFactory, PrescriberFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import TestCase, parse_response_to_soup


DISABLED_NIR = 'disabled id="id_nir"'
PRIOR_ACTION_SECTION_TITLE = "Action préalable à l'embauche"


class ProcessViewsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        cls.cities = create_test_cities(["54", "57"], num_per_department=2)

    def get_random_city(self):
        return random.choice(self.cities)

    def accept_job_application(
        self, job_application, post_data=None, city=None, assert_successful=True, job_description=None
    ):
        """
        This is not a test. It's a shortcut to process "apply:accept" view steps:
        - GET
        - POST: show the confirmation modal
        - POST: hide the modal and redirect to the next url.

        If needed a job description can be passed as parameter, as it is now mandatory for each hiring.
        If not provided, a new one will be created and linked to the given job application.
        """
        job_description = JobDescriptionFactory(siae=job_application.to_siae)

        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url_accept)
        self.assertContains(response, "Confirmation de l’embauche")
        # Make sure modal is hidden.
        assert response.headers.get("HX-Trigger") is None

        if not post_data:
            hiring_start_at = timezone.localdate()
            hiring_end_at = Approval.get_default_end_date(hiring_start_at)
            post_data = {
                "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
                "answer": "",
                "address_line_1": job_application.job_seeker.address_line_1,
                "post_code": job_application.job_seeker.post_code,
                "city": city.name,
                "city_slug": city.slug,
                "hired_job": job_description.pk,
            }

        response = self.client.post(url_accept, headers={"hx-request": "true"}, data=post_data)

        if assert_successful:
            assert (
                response.headers.get("HX-Trigger")
                == '{"modalControl": {"id": "js-confirmation-modal", "action": "show"}}'
            )
        else:
            assert response.headers.get("HX-Trigger") is None

        post_data = post_data | {"confirmed": "True"}
        response = self.client.post(url_accept, headers={"hx-request": "true"}, data=post_data)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        # django-htmx triggers a client side redirect when it receives a response with the HX-Redirect header.
        # It renders an HttpResponseRedirect subclass which, unfortunately, responds with a 200 status code.
        # I guess it's normal as it's an AJAX response.
        # See https://django-htmx.readthedocs.io/en/latest/http.html#django_htmx.http.HttpResponseClientRedirect # noqa
        if assert_successful:
            self.assertRedirects(response, next_url, status_code=200, fetch_redirect_response=False)

        return response, next_url

    def test_details_for_siae(self, *args, **kwargs):
        """Display the details of a job application."""

        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True, resume_link="")
        siae = job_application.to_siae
        siae_user = siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertContains(response, "Ce candidat a pris le contrôle de son compte utilisateur.")
        self.assertContains(response, format_nir(job_application.job_seeker.nir))
        self.assertContains(response, job_application.job_seeker.pole_emploi_id)
        self.assertContains(response, job_application.job_seeker.phone.replace(" ", ""))
        self.assertNotContains(response, PRIOR_ACTION_SECTION_TITLE)  # the SIAE is not a GEIQ

        job_application.job_seeker.created_by = siae_user
        job_application.job_seeker.phone = ""
        job_application.job_seeker.nir = ""
        job_application.job_seeker.pole_emploi_id = ""
        job_application.job_seeker.save()

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertContains(response, "Modifier les informations")
        self.assertContains(response, "Adresse : <span>Non renseignée</span>", html=True)
        self.assertContains(response, "Téléphone : <span>Non renseigné</span>", html=True)
        self.assertContains(response, "CV : <span>Non renseigné</span>", html=True)
        self.assertContains(response, "Identifiant Pôle emploi : <span>Non renseigné</span>", html=True)
        self.assertContains(response, "Numéro de sécurité sociale : <span>Non renseigné</span>", html=True)

        job_application.job_seeker.lack_of_nir_reason = LackOfNIRReason.TEMPORARY_NUMBER
        job_application.job_seeker.save()

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertContains(response, LackOfNIRReason.TEMPORARY_NUMBER.label)

        # Test resume presence:
        # 1/ Job seeker has a personal resume (technical debt).
        resume_link = "https://server.com/rockie-balboa.pdf"
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker__resume_link=resume_link, resume_link="", to_siae=siae
        )
        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertNotContains(response, "CV : <span>Non renseigné</span>", html=True)
        self.assertContains(response, resume_link)

        # 2/ Job application was sent with an attached resume
        new_resume_link = "https://server.com/sylvester-stallone.pdf"
        job_application = JobApplicationSentByJobSeekerFactory(to_siae=siae, resume_link=new_resume_link)
        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertContains(response, new_resume_link)
        self.assertNotContains(response, resume_link)

    def test_details_for_siae_hidden(self, *args, **kwargs):
        """A hidden job_application is not displayed."""

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, job_seeker__kind=UserKind.JOB_SEEKER, hidden_for_siae=True
        )
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        assert 404 == response.status_code

    def test_details_for_siae_as_prescriber(self, *args, **kwargs):
        """As a prescriber, I cannot access the job_applications details for SIAEs."""

        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        prescriber = job_application.sender_prescriber_organization.members.first()

        self.client.force_login(prescriber)

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        assert response.status_code == 404

    def test_details_for_prescriber(self, *args, **kwargs):
        """As a prescriber, I can access the job_applications details for prescribers."""

        job_application = JobApplicationFactory(
            with_approval=True, resume_link="", sent_by_authorized_prescriber_organisation=True
        )
        prescriber = job_application.sender_prescriber_organization.members.first()

        self.client.force_login(prescriber)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        # Job seeker nir is displayed
        self.assertContains(response, format_nir(job_application.job_seeker.nir))
        # Approval is displayed
        self.assertContains(response, "Numéro de PASS IAE")

        self.assertContains(response, "Adresse : <span>Non renseignée</span>", html=True)
        self.assertContains(response, "CV : <span>Non renseigné</span>", html=True)

        job_application.job_seeker.nir = ""
        job_application.job_seeker.save()
        response = self.client.get(url)
        self.assertContains(response, "Numéro de sécurité sociale : <span>Non renseigné</span>", html=True)

        job_application.job_seeker.lack_of_nir_reason = LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER
        job_application.job_seeker.save()
        response = self.client.get(url)
        self.assertContains(response, LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER.label, html=True)

    def test_details_for_prescriber_as_siae(self, *args, **kwargs):
        """As a SIAE user, I cannot access the job_applications details for prescribers."""

        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        assert response.status_code == 302

    def test_details_for_unauthorized_prescriber(self, *args, **kwargs):
        """As an unauthorized prescriber I cannot access personnal information of arbitrary job seekers"""
        prescriber = PrescriberFactory()
        job_application = JobApplicationFactory(
            job_seeker_with_address=True,
            job_seeker__first_name="Supersecretname",
            job_seeker__last_name="Unknown",
            sender=prescriber,
            sender_kind=job_applications_enums.SenderKind.PRESCRIBER,
        )
        self.client.force_login(prescriber)
        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertContains(response, format_nir(job_application.job_seeker.nir))
        self.assertContains(response, "Prénom : <b>S…</b>", html=True)
        self.assertContains(response, "Nom : <b>U…</b>", html=True)
        self.assertContains(response, '<span class="text-muted">S… U…</span>', html=True)
        self.assertNotContains(response, job_application.job_seeker.email)
        self.assertNotContains(response, job_application.job_seeker.phone)
        self.assertNotContains(response, job_application.job_seeker.post_code)
        self.assertNotContains(response, "Supersecretname")
        self.assertNotContains(response, "Unknown")

    def test_process(self, *args, **kwargs):
        """Ensure that the `process` transition is triggered."""

        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:process", kwargs={"job_application_id": job_application.pk})
        response = self.client.post(url)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        self.assertRedirects(response, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.state.is_processing

    def test_refuse(self, *args, **kwargs):
        """Ensure that the `refuse` transition is triggered."""

        states = [
            JobApplicationWorkflow.STATE_NEW,
            JobApplicationWorkflow.STATE_PROCESSING,
            JobApplicationWorkflow.STATE_PRIOR_TO_HIRE,
            JobApplicationWorkflow.STATE_POSTPONED,
        ]

        for state in states:
            with self.subTest(state=state):
                job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True, state=state)

                siae_user = job_application.to_siae.members.first()
                self.client.force_login(siae_user)

                url = reverse("apply:refuse", kwargs={"job_application_id": job_application.pk})
                response = self.client.get(url)
                assert response.status_code == 200

                post_data = {
                    "refusal_reason": job_applications_enums.RefusalReason.OTHER,
                    "answer": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                }
                response = self.client.post(url, data=post_data)
                next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
                self.assertRedirects(response, next_url)

                job_application = JobApplication.objects.get(pk=job_application.pk)
                assert job_application.state.is_refused

    def test_postpone(self, *args, **kwargs):
        """Ensure that the `postpone` transition is triggered."""

        states = [
            JobApplicationWorkflow.STATE_PROCESSING,
            JobApplicationWorkflow.STATE_PRIOR_TO_HIRE,
        ]

        for state in states:
            with self.subTest(state=state):
                job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True, state=state)
                siae_user = job_application.to_siae.members.first()
                self.client.force_login(siae_user)

                url = reverse("apply:postpone", kwargs={"job_application_id": job_application.pk})
                response = self.client.get(url)
                assert response.status_code == 200

                post_data = {"answer": ""}
                response = self.client.post(url, data=post_data)
                next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
                self.assertRedirects(response, next_url)

                job_application = JobApplication.objects.get(pk=job_application.pk)
                assert job_application.state.is_postponed

    def test_accept(self, *args, **kwargs):
        city = self.get_random_city()
        today = timezone.localdate()

        job_seeker = JobSeekerWithAddressFactory(city=city.name)
        address = {
            "address_line_1": job_seeker.address_line_1,
            "post_code": job_seeker.post_code,
            "city": city.name,
            "city_slug": city.slug,
        }
        siae = SiaeFactory(with_membership=True)
        siae_user = siae.members.first()
        self.client.force_login(siae_user)

        hiring_end_dates = [
            Approval.get_default_end_date(today),
            None,
        ]
        cases = list(product(hiring_end_dates, JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES))

        for hiring_end_at, state in cases:
            with self.subTest(hiring_end_at=hiring_end_at, state=state):
                job_application = JobApplicationFactory(
                    state=state,
                    job_seeker=job_seeker,
                    to_siae=siae,
                )
                previous_last_checked_at = job_seeker.last_checked_at

                # Good duration.
                hiring_start_at = today
                post_data = {
                    # Data for `JobSeekerPersonalDataForm`.
                    "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
                    # Data for `AcceptForm`.
                    "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                    "answer": "",
                    **address,
                }
                if hiring_end_at:
                    post_data["hiring_end_at"] = hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT)

                _, next_url = self.accept_job_application(job_application=job_application, post_data=post_data)

                job_application = JobApplication.objects.get(pk=job_application.pk)
                assert job_application.hiring_start_at == hiring_start_at
                assert job_application.hiring_end_at == hiring_end_at
                assert job_application.state.is_accepted

                # test how hiring_end_date is displayed
                response = self.client.get(next_url)
                # test case hiring_end_at
                if hiring_end_at:
                    self.assertContains(response, f"Fin : {hiring_end_at:%d}")
                else:
                    self.assertContains(response, "Fin : Non renseigné")
                # last_checked_at has been updated
                assert job_application.job_seeker.last_checked_at > previous_last_checked_at

        ##############
        # Exceptions #
        ##############
        job_application = JobApplicationFactory(
            state=state,
            job_seeker=job_seeker,
            to_siae=siae,
        )

        # Wrong dates.
        hiring_start_at = today
        hiring_end_at = Approval.get_default_end_date(hiring_start_at)
        # Force `hiring_start_at` in past.
        hiring_start_at = hiring_start_at - relativedelta(days=1)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "answer": "",
            **address,
        }
        response, _ = self.accept_job_application(
            job_application=job_application, post_data=post_data, assert_successful=False
        )
        self.assertFormError(response.context["form_accept"], "hiring_start_at", JobApplication.ERROR_START_IN_PAST)

        # Wrong dates: end < start.
        hiring_start_at = today
        hiring_end_at = hiring_start_at - relativedelta(days=1)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "answer": "",
            **address,
        }
        response, _ = self.accept_job_application(
            job_application=job_application, post_data=post_data, assert_successful=False
        )
        self.assertFormError(response.context["form_accept"], None, JobApplication.ERROR_END_IS_BEFORE_START)

        # No address provided.
        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_siae=siae,
        )

        hiring_start_at = today
        hiring_end_at = Approval.get_default_end_date(hiring_start_at)
        post_data = {
            # Data for `JobSeekerPersonalDataForm`.
            "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
            # Data for `AcceptForm`.
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "answer": "",
        }
        response, _ = self.accept_job_application(
            job_application=job_application, post_data=post_data, assert_successful=False
        )
        self.assertFormError(response.context["form_user_address"], "address_line_1", "Ce champ est obligatoire.")
        self.assertFormError(response.context["form_user_address"], "city", "Ce champ est obligatoire.")
        self.assertFormError(response.context["form_user_address"], "post_code", "Ce champ est obligatoire.")

        # No eligibility diagnosis -> if job_seeker has a valid eligibility diagnosis, it's OK
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker=job_seeker,
            to_siae=siae,
            eligibility_diagnosis=None,
        )
        post_data = {
            # Data for `JobSeekerPersonalDataForm`.
            "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
            # Data for `AcceptForm`.
            "hiring_start_at": today.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "answer": "",
            **address,
        }
        self.accept_job_application(job_application=job_application, post_data=post_data)

        # if no, should not see the confirm button, nor accept posted data
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker=job_seeker,
            to_siae=siae,
            eligibility_diagnosis=None,
        )
        for approval in job_application.job_seeker.approvals.all():
            approval.delete()
        job_application.job_seeker.eligibility_diagnoses.all().delete()
        post_data = {
            # Data for `JobSeekerPersonalDataForm`.
            "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
            # Data for `AcceptForm`.
            "hiring_start_at": today.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "answer": "",
            **address,
        }
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url_accept, follow=True)
        self.assertRedirects(
            response, reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        )
        assert "Cette candidature requiert un diagnostic d'éligibilité pour être acceptée." == str(
            list(response.context["messages"])[-1]
        )

    def test_accept_with_active_suspension(self, *args, **kwargs):
        """Test the `accept` transition with active suspension for active user"""
        city = self.get_random_city()
        today = timezone.localdate()
        # the old job of job seeker
        job_seeker_user = JobSeekerWithAddressFactory()
        old_job_application = JobApplicationFactory(
            with_approval=True,
            job_seeker=job_seeker_user,
            # Ensure that the old_job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=100),
        )
        # create suspension for the job seeker
        approval_job_seeker = old_job_application.approval
        siae_user = old_job_application.to_siae.members.first()
        susension_start_at = today
        suspension_end_at = today + relativedelta(days=50)

        SuspensionFactory(
            approval=approval_job_seeker,
            start_at=susension_start_at,
            end_at=suspension_end_at,
            created_by=siae_user,
            reason=Suspension.Reason.BROKEN_CONTRACT.value,
        )

        # Now, another Siae wants to hire the job seeker
        other_siae = SiaeFactory(with_membership=True)
        job_application = JobApplicationFactory(
            approval=approval_job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker=job_seeker_user,
            to_siae=other_siae,
        )
        other_siae_user = job_application.to_siae.members.first()

        # login with other siae
        self.client.force_login(other_siae_user)
        hiring_start_at = today + relativedelta(days=20)
        hiring_end_at = Approval.get_default_end_date(hiring_start_at)

        post_data = {
            # Data for `JobSeekerPersonalDataForm`.
            "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
            # Data for `AcceptForm`.
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "answer": "",
            "address_line_1": job_seeker_user.address_line_1,
            "post_code": job_seeker_user.post_code,
            "city": city.name,
            "city_slug": city.slug,
        }
        self.accept_job_application(job_application=job_application, post_data=post_data)
        get_job_application = JobApplication.objects.get(pk=job_application.pk)
        g_suspension = get_job_application.approval.suspension_set.in_progress().last()

        # The end date of suspension is set to d-1 of hiring start day
        assert g_suspension.end_at == get_job_application.hiring_start_at - relativedelta(days=1)
        # Check if the duration of approval was updated correctly
        assert get_job_application.approval.end_at == approval_job_seeker.end_at + relativedelta(
            days=(g_suspension.end_at - g_suspension.start_at).days
        )

    def test_accept_with_manual_approval_delivery(self, *args, **kwargs):
        """
        Test the "manual approval delivery mode" path of the view.
        """
        city = self.get_random_city()

        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            # The state of the 3 `pole_emploi_*` fields will trigger a manual delivery.
            job_seeker__nir="",
            job_seeker__pole_emploi_id="",
            job_seeker__lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_FORGOTTEN,
        )

        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        post_data = {
            # Data for `JobSeekerPersonalDataForm`.
            "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_application.job_seeker.lack_of_pole_emploi_id_reason,
            "lack_of_nir": True,
            "lack_of_nir_reason": LackOfNIRReason.TEMPORARY_NUMBER,
            # Data for `UserAddressForm`.
            "address_line_1": "11 rue des Lilas",
            "post_code": "57000",
            "city": city.name,
            "city_slug": city.slug,
            # Data for `AcceptForm`.
            "hiring_start_at": timezone.localdate().strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": (timezone.localdate() + relativedelta(days=360)).strftime(
                DuetDatePickerWidget.INPUT_DATE_FORMAT
            ),
            "answer": "",
        }

        self.accept_job_application(job_application=job_application, post_data=post_data)
        job_application.refresh_from_db()
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_MANUAL

    def test_accept_and_update_hiring_start_date_of_two_job_applications(self, *args, **kwargs):
        city = self.get_random_city()
        job_seeker = JobSeekerWithAddressFactory()
        base_for_post_data = {
            "address_line_1": job_seeker.address_line_1,
            "post_code": job_seeker.post_code,
            "city": city.name,
            "city_slug": city.slug,
            "pole_emploi_id": job_seeker.pole_emploi_id,
            "answer": "",
        }
        hiring_start_at = timezone.localdate() + relativedelta(months=2)
        hiring_end_at = hiring_start_at + relativedelta(months=2)
        approval_default_ending = Approval.get_default_end_date(start_at=hiring_start_at)

        # Send 3 job applications to 3 different structures
        job_application = JobApplicationFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )
        job_app_starting_earlier = JobApplicationFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )
        job_app_starting_later = JobApplicationFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )

        # SIAE 1 logs in and accepts the first job application.
        # The delivered approval should start at the same time as the contract.
        user = job_application.to_siae.members.first()
        self.client.force_login(user)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            **base_for_post_data,
        }

        self.accept_job_application(job_application=job_application, post_data=post_data)

        # First job application has been accepted.
        # All other job applications are obsolete.
        job_application.refresh_from_db()
        assert job_application.state.is_accepted
        assert job_application.approval.start_at == job_application.hiring_start_at
        assert job_application.approval.end_at == approval_default_ending
        self.client.logout()

        # SIAE 2 accepts the second job application
        # but its contract starts earlier than the approval delivered the first time.
        # Approval's starting date should be brought forward.
        user = job_app_starting_earlier.to_siae.members.first()
        hiring_start_at = hiring_start_at - relativedelta(months=1)
        hiring_end_at = hiring_start_at + relativedelta(months=2)
        approval_default_ending = Approval.get_default_end_date(start_at=hiring_start_at)
        job_app_starting_earlier.refresh_from_db()
        assert job_app_starting_earlier.state.is_obsolete

        self.client.force_login(user)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            **base_for_post_data,
        }
        self.accept_job_application(job_application=job_app_starting_earlier, post_data=post_data)
        job_app_starting_earlier.refresh_from_db()

        # Second job application has been accepted.
        # The job seeker has now two part-time jobs at the same time.
        assert job_app_starting_earlier.state.is_accepted
        assert job_app_starting_earlier.approval.start_at == job_app_starting_earlier.hiring_start_at
        assert job_app_starting_earlier.approval.end_at == approval_default_ending
        self.client.logout()

        # SIAE 3 accepts the third job application.
        # Its contract starts later than the corresponding approval.
        # Approval's starting date should not be updated.
        user = job_app_starting_later.to_siae.members.first()
        hiring_start_at = hiring_start_at + relativedelta(months=6)
        hiring_end_at = hiring_start_at + relativedelta(months=2)
        job_app_starting_later.refresh_from_db()
        assert job_app_starting_later.state.is_obsolete

        self.client.force_login(user)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            **base_for_post_data,
        }
        self.accept_job_application(job_application=job_app_starting_later, post_data=post_data)
        job_app_starting_later.refresh_from_db()

        # Third job application has been accepted.
        # The job seeker has now three part-time jobs at the same time.
        assert job_app_starting_later.state.is_accepted
        assert job_app_starting_later.approval.start_at == job_app_starting_earlier.hiring_start_at

    def test_accept_with_double_user(self, *args, **kwargs):
        city = self.get_random_city()

        siae = SiaeFactory(with_membership=True)
        job_seeker = JobSeekerWithAddressFactory(city=city.name)
        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker=job_seeker,
            to_siae=siae,
        )

        # Create a "PE Approval" that will be converted to a PASS IAE when accepting the process
        pole_emploi_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=job_seeker.pole_emploi_id, birthdate=job_seeker.birthdate
        )

        # Accept the job application for the first job seeker.
        self.client.force_login(siae.members.first())
        _, next_url = self.accept_job_application(job_application=job_application, city=city)
        response = self.client.get(next_url)
        assert "Un PASS IAE lui a déjà été délivré mais il est associé à un autre compte. " not in str(
            list(response.context["messages"])[0]
        )

        # This approval is found thanks to the PE Approval number
        approval = Approval.objects.get(number=pole_emploi_approval.number)
        assert approval.user == job_seeker

        # Now generate a job seeker that is "almost the same"
        almost_same_job_seeker = JobSeekerWithAddressFactory(
            city=city.name, pole_emploi_id=job_seeker.pole_emploi_id, birthdate=job_seeker.birthdate
        )
        another_job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker=almost_same_job_seeker,
            to_siae=siae,
        )

        # Gracefully display a message instead of just plain crashing
        _, next_url = self.accept_job_application(job_application=another_job_application, city=city)
        response = self.client.get(next_url)
        assert "Un PASS IAE lui a déjà été délivré mais il est associé à un autre compte. " in str(
            list(response.context["messages"])[0]
        )

    @override_settings(TALLY_URL="https://tally.so")
    def test_accept_nir_readonly(self, *args, **kwargs):
        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )

        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url_accept)
        self.assertContains(response, "Confirmation de l’embauche")
        # Check that the NIR field is disabled
        self.assertContains(response, DISABLED_NIR)
        self.assertContains(
            response,
            "Ce candidat a pris le contrôle de son compte utilisateur. Vous ne pouvez pas modifier ses informations.",
            html=True,
        )

        job_application.job_seeker.last_login = None
        job_application.job_seeker.created_by = PrescriberFactory()
        job_application.job_seeker.save()
        response = self.client.get(url_accept)
        self.assertContains(response, "Confirmation de l’embauche")
        # Check that the NIR field is disabled
        self.assertContains(response, DISABLED_NIR)
        self.assertContains(
            response,
            (
                f'<a href="https://tally.so/r/wzxQlg?jobapplication={job_application.pk}" target="_blank" '
                'rel="noopener">Demander la correction du numéro de sécurité sociale</a>'
            ),
            html=True,
        )

    def test_accept_no_nir_update(self, *args, **kwargs):
        city = self.get_random_city()

        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker__nir="",
        )
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        response = self.client.get(url_accept)
        self.assertContains(response, "Confirmation de l’embauche")
        # Check that the NIR field is not disabled
        self.assertNotContains(response, DISABLED_NIR)

        post_data = {
            # Data for `JobSeekerPersonalDataForm`.
            "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_application.job_seeker.lack_of_pole_emploi_id_reason,
            # Data for `UserAddressForm`.
            "address_line_1": "11 rue des Lilas",
            "post_code": "57000",
            "city": city.name,
            "city_slug": city.slug,
            # Data for `AcceptForm`.
            "hiring_start_at": timezone.localdate().strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": (timezone.localdate() + relativedelta(days=360)).strftime(
                DuetDatePickerWidget.INPUT_DATE_FORMAT
            ),
            "answer": "",
        }
        response = self.client.post(url_accept, headers={"hx-request": "true"}, data=post_data)
        self.assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)

        post_data["nir"] = "1234"
        response = self.client.post(url_accept, headers={"hx-request": "true"}, data=post_data)
        self.assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        self.assertFormError(
            response.context["form_personal_data"],
            "nir",
            "Le numéro de sécurité sociale est trop court (15 caractères autorisés).",
        )

        NEW_NIR = "197013625838386"
        post_data["nir"] = NEW_NIR

        self.accept_job_application(job_application=job_application, post_data=post_data)
        job_application.job_seeker.refresh_from_db()
        assert job_application.job_seeker.nir == NEW_NIR

    def test_accept_no_nir_other_user(self, *args, **kwargs):
        city = self.get_random_city()

        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker__nir="",
        )
        other_job_seeker = JobSeekerWithAddressFactory()
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        post_data = {
            # Data for `JobSeekerPersonalDataForm`.
            "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_application.job_seeker.lack_of_pole_emploi_id_reason,
            "nir": other_job_seeker.nir,
            # Data for `UserAddressForm`.
            "address_line_1": "11 rue des Lilas",
            "post_code": "57000",
            "city": city.name,
            "city_slug": city.slug,
            # Data for `AcceptForm`.
            "hiring_start_at": timezone.localdate().strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": (timezone.localdate() + relativedelta(days=360)).strftime(
                DuetDatePickerWidget.INPUT_DATE_FORMAT
            ),
            "answer": "",
        }
        response = self.client.post(url_accept, headers={"hx-request": "true"}, data=post_data)
        self.assertContains(
            response, "Le numéro de sécurité sociale est déjà associé à un autre utilisateur", html=True
        )
        self.assertFormError(
            response.context["form_personal_data"],
            None,
            "Ce numéro de sécurité sociale est déjà associé à un autre utilisateur.",
        )

    def test_accept_no_nir_update_with_reason(self, *args, **kwargs):
        city = self.get_random_city()

        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker__nir="",
        )
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        post_data = {
            # Data for `JobSeekerPersonalDataForm`.
            "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_application.job_seeker.lack_of_pole_emploi_id_reason,
            # Data for `UserAddressForm`.
            "address_line_1": "11 rue des Lilas",
            "post_code": "57000",
            "city": city.name,
            "city_slug": city.slug,
            # Data for `AcceptForm`.
            "hiring_start_at": timezone.localdate().strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": (timezone.localdate() + relativedelta(days=360)).strftime(
                DuetDatePickerWidget.INPUT_DATE_FORMAT
            ),
            "answer": "",
        }
        response = self.client.post(url_accept, headers={"hx-request": "true"}, data=post_data)
        self.assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)

        # Check the box
        post_data["lack_of_nir"] = True
        response = self.client.post(url_accept, headers={"hx-request": "true"}, data=post_data)
        self.assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        self.assertContains(response, "Veuillez sélectionner un motif pour continuer", html=True)

        post_data["lack_of_nir_reason"] = LackOfNIRReason.NO_NIR
        self.accept_job_application(job_application=job_application, post_data=post_data, assert_successful=True)
        job_application.job_seeker.refresh_from_db()
        assert job_application.job_seeker.lack_of_nir_reason == LackOfNIRReason.NO_NIR

    def test_accept_lack_of_nir_reason_update(self, *args, **kwargs):
        city = self.get_random_city()

        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker__nir="",
            job_seeker__lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER,
        )
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        response = self.client.get(url_accept)
        self.assertContains(response, "Confirmation de l’embauche")
        # Check that the NIR field is initially disabled
        # since the job seeker has a lack_of_nir_reason
        assert response.context["form_personal_data"].fields["nir"].disabled
        NEW_NIR = "197013625838386"

        post_data = {
            # Data for `JobSeekerPersonalDataForm`.
            "nir": NEW_NIR,
            "lack_of_nir_reason": job_application.job_seeker.lack_of_nir_reason,
            "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_application.job_seeker.lack_of_pole_emploi_id_reason,
            # Data for `UserAddressForm`.
            "address_line_1": "11 rue des Lilas",
            "post_code": "57000",
            "city": city.name,
            "city_slug": city.slug,
            # Data for `AcceptForm`.
            "hiring_start_at": timezone.localdate().strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": (timezone.localdate() + relativedelta(days=360)).strftime(
                DuetDatePickerWidget.INPUT_DATE_FORMAT
            ),
            "answer": "",
        }

        self.accept_job_application(job_application=job_application, post_data=post_data, assert_successful=True)
        job_application.job_seeker.refresh_from_db()
        # New NIR is set and the lack_of_nir_reason is cleaned
        assert not job_application.job_seeker.lack_of_nir_reason
        assert job_application.job_seeker.nir == NEW_NIR

    @override_settings(TALLY_URL="https://tally.so")
    def test_accept_lack_of_nir_reason_other_user(self, *args, **kwargs):
        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker__nir="",
            job_seeker__lack_of_nir_reason=LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER,
        )
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        response = self.client.get(url_accept)
        self.assertContains(response, "Confirmation de l’embauche")
        # Check that the NIR field is initially disabled
        # since the job seeker has a lack_of_nir_reason
        assert response.context["form_personal_data"].fields["nir"].disabled

        # Check that the tally link is there
        self.assertContains(
            response,
            (
                f'<a href="https://tally.so/r/wzxQlg?jobapplication={job_application.pk}" target="_blank" '
                'rel="noopener">Demander la correction du numéro de sécurité sociale</a>'
            ),
            html=True,
        )

    def test_eligibility(self, *args, **kwargs):
        """Test eligibility."""
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker=JobSeekerWithAddressFactory(with_address_in_qpv=True),
            eligibility_diagnosis=None,
        )

        assert job_application.state.is_processing
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_siae
        )
        assert not has_considered_valid_diagnoses

        criterion1 = AdministrativeCriteria.objects.level1().get(pk=1)
        criterion2 = AdministrativeCriteria.objects.level2().get(pk=5)
        criterion3 = AdministrativeCriteria.objects.level2().get(pk=15)

        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, "apply/includes/known_criteria.html", count=1)

        # Ensure that some criteria are mandatory.
        post_data = {
            f"{criterion1.key}": "false",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form_administrative_criteria"].errors

        post_data = {
            # Administrative criteria level 1.
            f"{criterion1.key}": "true",
            # Administrative criteria level 2.
            f"{criterion2.key}": "true",
            f"{criterion3.key}": "true",
        }
        response = self.client.post(url, data=post_data)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        self.assertRedirects(response, next_url)

        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_siae
        )
        assert has_considered_valid_diagnoses

        # Check diagnosis.
        eligibility_diagnosis = job_application.get_eligibility_diagnosis()
        assert eligibility_diagnosis.author == siae_user
        assert eligibility_diagnosis.author_kind == AuthorKind.EMPLOYER
        assert eligibility_diagnosis.author_siae == job_application.to_siae
        # Check administrative criteria.
        administrative_criteria = eligibility_diagnosis.administrative_criteria.all()
        assert 3 == administrative_criteria.count()
        assert criterion1 in administrative_criteria
        assert criterion2 in administrative_criteria
        assert criterion3 in administrative_criteria

    def test_eligibility_for_siae_not_subject_to_eligibility_rules(self, *args, **kwargs):
        """Test eligibility for an Siae not subject to eligibility rules."""

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_siae__kind=CompanyKind.GEIQ,
        )
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        assert response.status_code == 404

    def test_eligibility_for_siae_with_suspension_sanction(self, *args, **kwargs):
        """Test eligibility for an Siae that has been suspended."""

        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker=JobSeekerWithAddressFactory(),
        )
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=job_application.to_siae),
            suspension_dates=InclusiveDateRange(timezone.localdate()),
        )

        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertContains(
            response, "suite aux mesures prises dans le cadre du contrôle a posteriori", status_code=403
        )

    def test_eligibility_state_for_job_application(self, *args, **kwargs):
        """The eligibility diagnosis page must only be accessible
        in JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES states."""
        siae = SiaeFactory(with_membership=True)
        siae_user = siae.members.first()
        job_application = JobApplicationSentByJobSeekerFactory(to_siae=siae, job_seeker=JobSeekerWithAddressFactory())

        # Right states
        for state in JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES:
            job_application.state = state
            job_application.save()
            self.client.force_login(siae_user)
            url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
            response = self.client.get(url)
            assert response.status_code == 200
            self.client.logout()

        # Wrong state
        job_application.state = JobApplicationWorkflow.STATE_ACCEPTED
        job_application.save()
        self.client.force_login(siae_user)
        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        assert response.status_code == 404
        self.client.logout()

    def test_cancel(self, *args, **kwargs):
        # Hiring date is today: cancellation should be possible.
        job_application = JobApplicationFactory(with_approval=True, to_siae__subject_to_eligibility=True)
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)
        url = reverse("apply:cancel", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertContains(response, "Confirmer l'annulation de l'embauche")
        self.assertContains(
            response, "En validant, <b>vous renoncez aux aides au poste</b> liées à cette candidature pour tous"
        )
        self.assertNotContains(
            response,
            "En annulant cette embauche, vous confirmez que le salarié n’avait pas encore commencé à "
            "travailler dans votre structure.",
        )

        post_data = {
            "confirm": "true",
        }
        response = self.client.post(url, data=post_data)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        self.assertRedirects(response, next_url)

        job_application.refresh_from_db()
        assert job_application.state.is_cancelled

    def test_cancel_saie_not_subject_to_eligibility(self, *args, **kwargs):
        # Hiring date is today: cancellation should be possible.
        job_application = JobApplicationFactory(with_approval=True, to_siae__not_subject_to_eligibility=True)
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)
        url = reverse("apply:cancel", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertContains(response, "Confirmer l'annulation de l'embauche")
        self.assertNotContains(
            response, "En validant, <b>vous renoncez aux aides au poste</b> liées à cette candidature pour tous"
        )
        self.assertContains(
            response,
            "En annulant cette embauche, vous confirmez que le salarié n’avait pas encore commencé à "
            "travailler dans votre structure.",
        )
        # Not need to the form POST, only the warning above changes

    def test_cannot_cancel(self, *args, **kwargs):
        job_application = JobApplicationFactory(
            with_approval=True,
            hiring_start_at=timezone.localdate() + relativedelta(days=1),
        )
        siae_user = job_application.to_siae.members.first()
        # Add a blocking employee record
        EmployeeRecordFactory(job_application=job_application, status=Status.PROCESSED)

        self.client.force_login(siae_user)
        url = reverse("apply:cancel", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        self.assertRedirects(response, next_url)

        job_application.refresh_from_db()
        assert not job_application.state.is_cancelled

    def test_accept_after_cancel(self, *args, **kwargs):
        # A canceled job application is not linked to an approval
        # unless the job seeker has an accepted job application.
        city = self.get_random_city()
        job_seeker = JobSeekerWithAddressFactory(city=city.name)
        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_CANCELLED,
            job_seeker=job_seeker,
        )
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        self.accept_job_application(job_application=job_application, city=city)

        job_application.refresh_from_db()
        assert job_seeker.approvals.count() == 1
        approval = job_seeker.approvals.first()
        assert approval.start_at == job_application.hiring_start_at
        assert job_application.state.is_accepted

    def test_archive(self, *args, **kwargs):
        """Ensure that when an SIAE archives a job_application, the hidden_for_siae flag is updated."""

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, state=JobApplicationWorkflow.STATE_CANCELLED
        )
        assert job_application.state.is_cancelled
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:archive", kwargs={"job_application_id": job_application.pk})

        cancelled_states = [
            JobApplicationWorkflow.STATE_REFUSED,
            JobApplicationWorkflow.STATE_CANCELLED,
            JobApplicationWorkflow.STATE_OBSOLETE,
        ]

        response = self.client.post(url)

        qs = urlencode({"states": cancelled_states}, doseq=True)
        url = reverse("apply:list_for_siae")
        next_url = f"{url}?{qs}"
        self.assertRedirects(response, next_url)

        job_application.refresh_from_db()
        assert job_application.hidden_for_siae


class ProcessTemplatesTest(TestCase):
    """
    Test actions available in the details template for the different.
    states of a job application.
    """

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.job_application = JobApplicationFactory(eligibility_diagnosis=None)
        cls.siae_user = cls.job_application.to_siae.members.first()

        kwargs = {"job_application_id": cls.job_application.pk}
        cls.url_details = reverse("apply:details_for_siae", kwargs=kwargs)
        cls.url_process = reverse("apply:process", kwargs=kwargs)
        cls.url_eligibility = reverse("apply:eligibility", kwargs=kwargs)
        cls.url_refuse = reverse("apply:refuse", kwargs=kwargs)
        cls.url_postpone = reverse("apply:postpone", kwargs=kwargs)
        cls.url_accept = reverse("apply:accept", kwargs=kwargs)

    def test_details_template_for_state_new(self):
        """Test actions available when the state is new."""
        self.client.force_login(self.siae_user)
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertContains(response, self.url_process)
        self.assertNotContains(response, self.url_eligibility)
        self.assertContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertNotContains(response, self.url_accept)

    def test_details_template_for_state_processing(self):
        """Test actions available when the state is processing."""
        self.client.force_login(self.siae_user)
        self.job_application.state = JobApplicationWorkflow.STATE_PROCESSING
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertContains(response, self.url_eligibility)
        self.assertContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertNotContains(response, self.url_accept)

    def test_details_template_for_state_prior_to_hire(self):
        """Test actions available when the state is prior_to_hire."""
        self.client.force_login(self.siae_user)
        self.job_application.state = JobApplicationWorkflow.STATE_PRIOR_TO_HIRE
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertContains(response, self.url_eligibility)
        self.assertContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertNotContains(response, self.url_accept)

    def test_details_template_for_state_processing_but_suspended_siae(self):
        """Test actions available when the state is processing but SIAE is suspended"""
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=self.job_application.to_siae),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )
        self.client.force_login(self.siae_user)
        self.job_application.state = JobApplicationWorkflow.STATE_PROCESSING
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertNotContains(response, self.url_eligibility)
        self.assertContains(
            response,
            (
                "Vous ne pouvez pas valider les critères d'éligibilité suite aux "
                "mesures prises dans le cadre du contrôle a posteriori"
            ),
        )
        self.assertContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertNotContains(response, self.url_accept)

    def test_details_template_for_state_postponed(self):
        """Test actions available when the state is postponed."""
        self.client.force_login(self.siae_user)
        self.job_application.state = JobApplicationWorkflow.STATE_POSTPONED
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertContains(response, self.url_eligibility)
        self.assertContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertNotContains(response, self.url_accept)

    def test_details_template_for_state_postponed_valid_diagnosis(self):
        """Test actions available when the state is postponed."""
        self.client.force_login(self.siae_user)
        EligibilityDiagnosisFactory(job_seeker=self.job_application.job_seeker)
        self.job_application.state = JobApplicationWorkflow.STATE_POSTPONED
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertNotContains(response, self.url_eligibility)
        self.assertContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertContains(response, self.url_accept)

    def test_details_template_for_state_obsolete(self):
        self.client.force_login(self.siae_user)
        self.job_application.state = JobApplicationWorkflow.STATE_OBSOLETE
        self.job_application.save()

        response = self.client.get(self.url_details)

        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertContains(response, self.url_eligibility)
        self.assertNotContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertNotContains(response, self.url_accept)

    def test_details_template_for_state_obsolete_valid_diagnosis(self):
        self.client.force_login(self.siae_user)
        EligibilityDiagnosisFactory(job_seeker=self.job_application.job_seeker)
        self.job_application.state = JobApplicationWorkflow.STATE_OBSOLETE
        self.job_application.save()

        response = self.client.get(self.url_details)

        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertNotContains(response, self.url_eligibility)
        self.assertNotContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertContains(response, self.url_accept)

    def test_details_template_for_state_refused(self):
        """Test actions available for other states."""
        self.client.force_login(self.siae_user)
        self.job_application.state = JobApplicationWorkflow.STATE_REFUSED
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertContains(response, self.url_eligibility)
        self.assertNotContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertNotContains(response, self.url_accept)

    def test_details_template_for_state_refused_valid_diagnosis(self):
        """Test actions available for other states."""
        self.client.force_login(self.siae_user)
        EligibilityDiagnosisFactory(job_seeker=self.job_application.job_seeker)
        self.job_application.state = JobApplicationWorkflow.STATE_REFUSED
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertNotContains(response, self.url_eligibility)
        self.assertNotContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertContains(response, self.url_accept)

    def test_details_template_for_state_canceled(self):
        """Test actions available for other states."""
        self.client.force_login(self.siae_user)
        self.job_application.state = JobApplicationWorkflow.STATE_CANCELLED
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertContains(response, self.url_eligibility)
        self.assertNotContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertNotContains(response, self.url_accept)

    def test_details_template_for_state_canceled_valid_diagnosis(self):
        """Test actions available for other states."""
        self.client.force_login(self.siae_user)
        EligibilityDiagnosisFactory(job_seeker=self.job_application.job_seeker)
        self.job_application.state = JobApplicationWorkflow.STATE_CANCELLED
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertNotContains(response, self.url_eligibility)
        self.assertNotContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertContains(response, self.url_accept)

    def test_details_template_for_state_accepted(self):
        """Test actions available for other states."""
        self.client.force_login(self.siae_user)
        self.job_application.state = JobApplicationWorkflow.STATE_ACCEPTED
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertNotContains(response, self.url_eligibility)
        self.assertNotContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertNotContains(response, self.url_accept)


@pytest.mark.usefixtures("unittest_compatibility")
class ProcessTransferJobApplicationTest(TestCase):
    TRANSFER_TO_OTHER_SIAE_SENTENCE = "Transférer cette candidature vers"

    def test_job_application_transfer_disabled_for_lone_users(self):
        # A user member of only one SIAE
        # must not be able to transfer a job application to another SIAE
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            to_siae=siae,
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )

        self.client.force_login(user)
        response = self.client.get(
            reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        )

        self.assertNotContains(response, self.TRANSFER_TO_OTHER_SIAE_SENTENCE)

    def test_job_application_transfer_disabled_for_bad_state(self):
        # A user member of only one SIAE must not be able to transfert
        # to another SIAE
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        job_application_1 = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, to_siae=siae, state=JobApplicationWorkflow.STATE_NEW
        )
        job_application_2 = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, to_siae=siae, state=JobApplicationWorkflow.STATE_ACCEPTED
        )

        self.client.force_login(user)
        response = self.client.get(
            reverse("apply:details_for_siae", kwargs={"job_application_id": job_application_1.pk})
        )
        self.assertNotContains(response, self.TRANSFER_TO_OTHER_SIAE_SENTENCE)

        response = self.client.get(
            reverse("apply:details_for_siae", kwargs={"job_application_id": job_application_2.pk})
        )

        self.assertNotContains(response, self.TRANSFER_TO_OTHER_SIAE_SENTENCE)

    def test_job_application_transfer_enabled(self):
        # A user member of several SIAE can transfer a job application
        siae = SiaeFactory(with_membership=True)
        other_siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        other_siae.members.add(user)
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            to_siae=siae,
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )

        assert 2 == user.companymembership_set.count()

        self.client.force_login(user)
        response = self.client.get(
            reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        )
        self.assertContains(response, self.TRANSFER_TO_OTHER_SIAE_SENTENCE)

    def test_job_application_transfer_redirection(self):
        # After transfering a job application,
        # user must be redirected to job application list
        # with a nice message
        siae = SiaeFactory(with_membership=True)
        other_siae = SiaeFactory(with_membership=True, for_snapshot=True)
        user = siae.members.first()
        other_siae.members.add(user)
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            to_siae=siae,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker__for_snapshot=True,
            job_seeker__first_name="<>html escaped<>",
        )
        transfer_url = reverse("apply:transfer", kwargs={"job_application_id": job_application.pk})

        self.client.force_login(user)
        response = self.client.get(
            reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        )

        self.assertContains(response, self.TRANSFER_TO_OTHER_SIAE_SENTENCE)
        self.assertContains(response, f"transfer_confirmation_modal_{other_siae.pk}")
        self.assertContains(response, "target_siae_id")
        self.assertContains(response, transfer_url)

        # Confirm from modal window
        post_data = {"target_siae_id": other_siae.pk}
        response = self.client.post(transfer_url, data=post_data, follow=True)
        messages = list(response.context.get("messages"))

        self.assertRedirects(response, reverse("apply:list_for_siae"))
        assert messages
        assert len(messages) == 1
        assert str(messages[0]) == self.snapshot(name="job application transfer message")

    def test_job_application_transfer_without_rights(self):
        siae = SiaeFactory()
        other_siae = SiaeFactory()
        user = JobSeekerFactory()
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            to_siae=siae,
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )
        # Forge query
        self.client.force_login(user)
        post_data = {"target_siae_id": other_siae.pk}
        transfer_url = reverse("apply:transfer", kwargs={"job_application_id": job_application.pk})
        response = self.client.post(transfer_url, data=post_data)
        assert response.status_code == 404


@pytest.mark.parametrize("reason", ["prevent_objectives", "non_eligible"])
def test_refuse_jobapplication_geiq_reasons(client, reason):
    job_application = JobApplicationFactory(
        sent_by_authorized_prescriber_organisation=True,
        state=JobApplicationWorkflow.STATE_PROCESSING,
        to_siae__kind=CompanyKind.GEIQ,
    )
    assert job_application.state.is_processing
    siae_user = job_application.to_siae.members.first()
    client.force_login(siae_user)

    url = reverse("apply:refuse", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)
    assert response.status_code == 200

    post_data = {
        "refusal_reason": reason,
        "answer": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
    }
    response = client.post(url, data=post_data)
    assert response.context["form"].errors == {
        "refusal_reason": [f"Sélectionnez un choix valide. {reason} n’en fait pas partie."]
    }


def test_details_for_prescriber_geiq(client):
    job_application = JobApplicationFactory(
        sent_by_authorized_prescriber_organisation=True,
        state=JobApplicationWorkflow.STATE_PROCESSING,
        with_geiq_eligibility_diagnosis_from_prescriber=True,
    )
    prescriber = job_application.sender_prescriber_organization.members.first()
    client.force_login(prescriber)

    url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)
    assert response.status_code == 200

    assert response.context["geiq_eligibility_diagnosis"] == job_application.geiq_eligibility_diagnosis


def test_accept_button(client):
    job_application = JobApplicationFactory(
        state=JobApplicationWorkflow.STATE_PROCESSING,
        to_siae__kind=CompanyKind.GEIQ,
    )
    accept_url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
    DIRECT_ACCEPT_BUTTON = f"""<a href="{accept_url}" class="btn btn-primary btn-block btn-ico">
            <i class="ri-check-line font-weight-medium" aria-hidden="true"></i>
            <span>Accepter cette candidature</span>
        </a>"""
    client.force_login(job_application.to_siae.members.first())
    response = client.get(reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk}))
    # GEIQ without GEIQ diagnosis: we get the modals
    assertNotContains(response, DIRECT_ACCEPT_BUTTON)

    job_application.to_siae.kind = CompanyKind.AI
    job_application.to_siae.save(update_fields=("kind",))

    response = client.get(reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk}))
    assertContains(response, DIRECT_ACCEPT_BUTTON)


def test_add_prior_action_new(client):
    # State is new
    job_application = JobApplicationFactory(to_siae__kind=CompanyKind.GEIQ)
    client.force_login(job_application.to_siae.members.first())
    add_prior_action_url = reverse("apply:add_prior_action", kwargs={"job_application_id": job_application.pk})
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.AFPR,
            "start_at": timezone.localdate(),
            "end_at": timezone.localdate() + relativedelta(days=2),
        },
    )
    assert response.status_code == 403
    assert not job_application.prior_actions.exists()


def test_add_prior_action_processing(client):
    job_application = JobApplicationFactory(
        to_siae__kind=CompanyKind.GEIQ, state=JobApplicationWorkflow.STATE_PROCESSING
    )
    client.force_login(job_application.to_siae.members.first())
    add_prior_action_url = reverse("apply:add_prior_action", kwargs={"job_application_id": job_application.pk})
    today = timezone.localdate()
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.AFPR,
            "start_at": today,
            "end_at": today + relativedelta(days=2),
        },
    )
    assert response.status_code == 200
    job_application.refresh_from_db()
    assert job_application.state.is_prior_to_hire
    prior_action = job_application.prior_actions.get()
    assert prior_action.action == job_applications_enums.Prequalification.AFPR
    assert prior_action.dates.lower == today
    assert prior_action.dates.upper == today + relativedelta(days=2)

    # State is accepted
    job_application.state = JobApplicationWorkflow.STATE_ACCEPTED
    job_application.save(update_fields=("state",))
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.POE,
            "start_at": timezone.localdate(),
            "end_at": timezone.localdate() + relativedelta(days=2),
        },
    )
    assert response.status_code == 403
    assert not job_application.prior_actions.filter(action=job_applications_enums.Prequalification.POE).exists()

    # State is processing but SIAE is not a GEIQ
    job_application = JobApplicationFactory(
        to_siae__kind=CompanyKind.AI, state=JobApplicationWorkflow.STATE_PROCESSING
    )
    client.force_login(job_application.to_siae.members.first())
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.AFPR,
            "start_at": timezone.localdate(),
            "end_at": timezone.localdate() + relativedelta(days=2),
        },
    )
    assert response.status_code == 404
    assert not job_application.prior_actions.exists()


def test_modify_prior_action(client):
    job_application = JobApplicationFactory(
        to_siae__kind=CompanyKind.GEIQ, state=JobApplicationWorkflow.STATE_POSTPONED
    )
    prior_action = PriorActionFactory(
        job_application=job_application, action=job_applications_enums.Prequalification.AFPR
    )
    client.force_login(job_application.to_siae.members.first())
    modify_prior_action_url = reverse(
        "apply:modify_prior_action",
        kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action.pk},
    )
    new_start_date = timezone.localdate() - relativedelta(days=10)
    new_end_date = new_start_date + relativedelta(days=6)
    response = client.post(
        modify_prior_action_url,
        data={
            "action": job_applications_enums.ProfessionalSituationExperience.PMSMP,
            "start_at": new_start_date,
            "end_at": new_end_date,
        },
    )
    assert response.status_code == 200
    prior_action.refresh_from_db()
    assert prior_action.dates.lower == new_start_date
    assert prior_action.dates.upper == new_end_date
    assert prior_action.action == job_applications_enums.ProfessionalSituationExperience.PMSMP

    job_application.state = JobApplicationWorkflow.STATE_ACCEPTED
    job_application.save(update_fields=("state",))
    response = client.post(
        modify_prior_action_url,
        data={
            "action": job_applications_enums.ProfessionalSituationExperience.MRS,
            "start_at": new_start_date,
            "end_at": new_end_date,
        },
    )
    assert response.status_code == 403
    prior_action.refresh_from_db()
    assert prior_action.action == job_applications_enums.ProfessionalSituationExperience.PMSMP


def test_delete_prior_action_accepted(client):
    job_application = JobApplicationFactory(
        to_siae__kind=CompanyKind.GEIQ, state=JobApplicationWorkflow.STATE_ACCEPTED
    )
    prior_action = PriorActionFactory(
        job_application=job_application, action=job_applications_enums.Prequalification.AFPR
    )
    client.force_login(job_application.to_siae.members.first())
    delete_prior_action_url = reverse(
        "apply:delete_prior_action",
        kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action.pk},
    )
    response = client.post(delete_prior_action_url, data={})
    # Once the application is accepted you cannot delete prior actions
    assert response.status_code == 403
    prior_action.refresh_from_db()


@pytest.mark.parametrize("with_geiq_diagnosis", [True, False])
def test_delete_prior_action(client, with_geiq_diagnosis):
    job_application = JobApplicationFactory(
        to_siae__kind=CompanyKind.GEIQ, state=JobApplicationWorkflow.STATE_PROCESSING
    )
    prior_action1 = PriorActionFactory(
        job_application=job_application, action=job_applications_enums.Prequalification.AFPR
    )
    prior_action2 = PriorActionFactory(
        job_application=job_application, action=job_applications_enums.Prequalification.AFPR
    )
    user = job_application.to_siae.members.first()
    if with_geiq_diagnosis:
        GEIQEligibilityDiagnosisFactory(
            job_seeker=job_application.job_seeker,
            author_geiq=job_application.to_siae,
            author=user,
            author_kind=AuthorKind.GEIQ,
        )
    # Create transition logs
    job_application.move_to_prior_to_hire(user=user)
    delete_prior_action1_url = reverse(
        "apply:delete_prior_action",
        kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action1.pk},
    )
    delete_prior_action2_url = reverse(
        "apply:delete_prior_action",
        kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action2.pk},
    )
    client.force_login(user)
    details_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
    response = client.get(details_url)
    simulated_page = parse_response_to_soup(response, selector="#main")

    # Delete first action
    response = client.post(delete_prior_action1_url, data={})
    assert response.status_code == 200
    update_page_with_htmx(
        simulated_page,
        f"form[hx-post='{delete_prior_action1_url}']",
        response,
    )
    job_application.refresh_from_db()
    assert job_application.prior_actions.count() == 1
    assert job_application.state.is_prior_to_hire

    # Check that a fresh reload gets us in the same state
    response = client.get(details_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)

    # Delete second action
    response = client.post(delete_prior_action2_url, data={})
    assert response.status_code == 200
    update_page_with_htmx(
        simulated_page,
        f"#delete_prior_action_{ prior_action2.pk }_modal > div > div > div > form",
        response,
    )
    job_application.refresh_from_db()
    assert job_application.prior_actions.count() == 0
    assert job_application.state.is_processing

    # Check that a fresh reload gets us in the same state
    response = client.get(details_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)


def test_htmx_add_prior_action_and_cancel(client):
    job_application = JobApplicationFactory(
        to_siae__kind=CompanyKind.GEIQ, state=JobApplicationWorkflow.STATE_PROCESSING
    )
    client.force_login(job_application.to_siae.members.first())
    details_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
    response = client.get(details_url)
    simulated_page = parse_response_to_soup(response, selector="#main")

    add_prior_action_url = reverse("apply:add_prior_action", kwargs={"job_application_id": job_application.pk})
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.AFPR,
        },
    )
    update_page_with_htmx(simulated_page, "#add_prior_action > form", response)
    # Click on Annuler
    response = client.get(add_prior_action_url)
    update_page_with_htmx(
        simulated_page,
        "#add_prior_action > form > div > button[hx-get]",
        response,
    )

    # Check that a fresh reload gets us in the same state
    response = client.get(details_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)


def test_htmx_modify_prior_action_and_cancel(client):
    job_application = JobApplicationFactory(
        to_siae__kind=CompanyKind.GEIQ, state=JobApplicationWorkflow.STATE_PROCESSING
    )
    prior_action = PriorActionFactory(job_application=job_application)
    client.force_login(job_application.to_siae.members.first())
    details_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
    response = client.get(details_url)
    simulated_page = parse_response_to_soup(response, selector="#main")

    modify_prior_action_url = reverse(
        "apply:modify_prior_action",
        kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action.pk},
    )
    response = client.get(modify_prior_action_url + "?modify=")
    update_page_with_htmx(
        simulated_page,
        f"#prior-action-{ prior_action.pk }-modify-btn",
        response,
    )
    # Click on Annuler
    response = client.get(modify_prior_action_url)
    update_page_with_htmx(simulated_page, f"#prior-action-{ prior_action.pk } > form > div > button[hx-get]", response)

    # Check that a fresh reload gets us in the same state
    response = client.get(details_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)


@pytest.mark.parametrize("with_geiq_diagnosis", [True, False])
def test_details_for_siae_with_prior_action(client, with_geiq_diagnosis):
    job_application = JobApplicationFactory(to_siae__kind=CompanyKind.GEIQ)
    user = job_application.to_siae.members.first()
    client.force_login(user)
    if with_geiq_diagnosis:
        GEIQEligibilityDiagnosisFactory(
            job_seeker=job_application.job_seeker,
            author_geiq=job_application.to_siae,
            author=user,
            author_kind=AuthorKind.GEIQ,
        )

    details_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
    response = client.get(details_url)
    # The job application is still new
    assertNotContains(response, PRIOR_ACTION_SECTION_TITLE)

    # Switch state to processing
    response = client.post(reverse("apply:process", kwargs={"job_application_id": job_application.pk}))
    assertRedirects(response, details_url)
    job_application.refresh_from_db()
    assert job_application.state == JobApplicationWorkflow.STATE_PROCESSING

    END_AT_LABEL = "Date de fin prévisionnelle"
    MISSING_FIELD_MESSAGE = "Ce champ est obligatoire"
    ADD_AN_ACTION_SELECTED = '<option value="" selected>Ajouter une action</option>'

    # Now the prior action section is visible
    response = client.get(details_url)
    assertContains(response, PRIOR_ACTION_SECTION_TITLE)
    # With PriorActionForm
    assertContains(response, ADD_AN_ACTION_SELECTED)
    # but not the dates fields
    assertNotContains(response, END_AT_LABEL)

    simulated_page = parse_response_to_soup(response, selector="#main")

    add_prior_action_url = reverse("apply:add_prior_action", kwargs={"job_application_id": job_application.pk})
    # Select the action type
    response = client.post(add_prior_action_url, data={"action": job_applications_enums.Prequalification.AFPR})
    update_page_with_htmx(simulated_page, "#add_prior_action > form", response)

    # To get access to date fields
    assertContains(response, END_AT_LABEL)
    assertNotContains(response, MISSING_FIELD_MESSAGE)
    assertNotContains(response, ADD_AN_ACTION_SELECTED)  # since AFPR is selected

    # Check when posting with missing fields
    response = client.post(
        add_prior_action_url, data={"action": job_applications_enums.Prequalification.AFPR, "start_at": ""}
    )
    assertContains(response, END_AT_LABEL)
    assert response.context["form"].has_error("start_at")
    assert response.context["form"].has_error("end_at")
    assertContains(response, MISSING_FIELD_MESSAGE)
    update_page_with_htmx(simulated_page, "#add_prior_action > form", response)

    # Check basic consistency on dates
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.AFPR,
            "start_at": timezone.localdate(),
            "end_at": timezone.localdate() - relativedelta(days=2),
        },
    )
    assertContains(response, "La date de fin prévisionnelle doit être postérieure à la date de début")
    update_page_with_htmx(simulated_page, "#add_prior_action > form", response)

    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.AFPR,
            "start_at": timezone.localdate(),
            "end_at": timezone.localdate() + relativedelta(days=2),
        },
    )
    assertContains(response, "Type : <b>Pré-qualification</b>", html=True)
    assertContains(response, "Nom : <b>AFPR</b>", html=True)
    # A new form accepting a new action is back
    assertContains(response, ADD_AN_ACTION_SELECTED)
    update_page_with_htmx(simulated_page, "#add_prior_action > form", response)

    job_application.refresh_from_db()
    assert job_application.state == JobApplicationWorkflow.STATE_PRIOR_TO_HIRE
    prior_action = job_application.prior_actions.get()
    assert prior_action.action == job_applications_enums.Prequalification.AFPR

    # Check that a full reload gets us an equivalent HTML
    response = client.get(details_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)
    # Let's modify the prior action
    modify_prior_action_url = reverse(
        "apply:modify_prior_action",
        kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action.pk},
    )
    response = client.get(modify_prior_action_url + "?modify=")
    update_page_with_htmx(simulated_page, f"#prior-action-{ prior_action.pk }-modify-btn", response)
    response = client.post(
        modify_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.POE,
            "start_at": timezone.localdate(),
            "end_at": timezone.localdate() + relativedelta(days=2),
        },
    )
    update_page_with_htmx(simulated_page, f"#prior-action-{ prior_action.pk } > form", response)
    prior_action.refresh_from_db()
    assert prior_action.action == job_applications_enums.Prequalification.POE
    # Check that a full reload gets us an equivalent HTML
    response = client.get(details_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)


def test_precriber_details_with_older_valid_approval(client, faker):
    # Ensure that the approval details are displayed for a prescriber
    # when the job seeker has a valid approval created on an older approval
    old_job_application = JobApplicationFactory(with_approval=True, hiring_start_at=faker.past_date(start_date="-3m"))
    new_job_application = JobApplicationSentByPrescriberOrganizationFactory(job_seeker=old_job_application.job_seeker)
    po_member = new_job_application.sender_prescriber_organization.members.first()
    client.force_login(po_member)
    response = client.get(
        reverse("apply:details_for_prescriber", kwargs={"job_application_id": new_job_application.pk})
    )
    # Must display approval status template (tested in many other places)
    assertTemplateUsed(response, template_name="approvals/includes/status.html")


@pytest.mark.parametrize(
    "inverted_vae_contract,expected_predicate", [(True, assertContains), (False, assertNotContains)]
)
def test_details_for_geiq_with_inverted_vae_contract(client, inverted_vae_contract, expected_predicate):
    # GEIQ: check that contract type is displayed in details
    job_application = JobApplicationFactory(
        state=JobApplicationWorkflow.STATE_ACCEPTED,
        to_siae__kind=CompanyKind.GEIQ,
        contract_type=ContractType.PROFESSIONAL_TRAINING,
        inverted_vae_contract=inverted_vae_contract,
    )

    user = job_application.to_siae.members.first()
    client.force_login(user)

    response = client.get(reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk}))

    inverted_vae_text = "associé à une VAE inversée"

    assertContains(response, job_application.get_contract_type_display())
    expected_predicate(response, inverted_vae_text)


@pytest.mark.parametrize("qualification_type", job_applications_enums.QualificationType)
def test_reload_qualification_fields(qualification_type, client, snapshot):
    siae = SiaeFactory(pk=10, kind=CompanyKind.GEIQ, with_membership=True)
    siae_member = siae.members.first()
    client.force_login(siae_member)
    url = reverse("apply:reload_qualification_fields", kwargs={"siae_pk": siae.pk})
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
    assert response.content.decode() == snapshot()


def test_reload_qualification_fields_404(client):
    siae = SiaeFactory(kind=CompanyKind.GEIQ, with_membership=True)
    siae_member = siae.members.first()
    client.force_login(siae_member)
    url = reverse("apply:reload_qualification_fields", kwargs={"siae_pk": 0})
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
    "contract_type", [value for value, _label in ContractType.choices_for_company_kind(CompanyKind.GEIQ)]
)
def test_reload_contract_type_and_options(contract_type, client, snapshot):
    siae = SiaeFactory(pk=10, kind=CompanyKind.GEIQ, with_membership=True)
    siae_member = siae.members.first()
    client.force_login(siae_member)
    url = reverse("apply:reload_contract_type_and_options", kwargs={"siae_pk": siae.pk})
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
    assert response.content.decode() == snapshot()


def test_reload_contract_type_and_options_404(client):
    siae = SiaeFactory(kind=CompanyKind.GEIQ, with_membership=True)
    siae_member = siae.members.first()
    client.force_login(siae_member)
    url = reverse("apply:reload_contract_type_and_options", kwargs={"siae_pk": 0})
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


def test_htmx_reload_contract_type_and_options(client, snapshot):
    job_application = JobApplicationFactory(
        to_siae__kind=CompanyKind.GEIQ, state=JobApplicationWorkflow.STATE_PROCESSING
    )
    siae_member = job_application.to_siae.members.first()
    client.force_login(siae_member)
    accept_url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
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
    response = client.post(accept_url, data=data)
    form_soup = parse_response_to_soup(response, selector="#acceptForm")

    # Update form soup with htmx call
    reload_url = reverse("apply:reload_contract_type_and_options", kwargs={"siae_pk": job_application.to_siae.pk})
    data["contract_type"] = ContractType.PERMANENT
    htmx_response = client.post(
        reload_url,
        data=data,
    )
    update_page_with_htmx(form_soup, "#id_contract_type", htmx_response)

    # Check that a complete re-POST returns the exact same form
    response = client.post(accept_url, data=data)
    reloaded_form_soup = parse_response_to_soup(response, selector="#acceptForm")
    assertSoupEqual(form_soup, reloaded_form_soup)


# Hirings must now be linked to a job description

ACTIVE_JOBS_LABEL = "Postes ouverts au recrutement"
INACTIVE_JOBS_LABEL = "Postes fermés au recrutement"
JOB_DETAILS_LABEL = "Préciser le nom du poste (code ROME)"


def test_select_job_description_for_job_application(client):
    create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
    job_application = JobApplicationFactory(
        to_siae__kind=CompanyKind.EI, state=JobApplicationWorkflow.STATE_PROCESSING
    )
    user = job_application.to_siae.members.first()

    client.force_login(user)
    response = client.get(reverse("apply:accept", kwargs={"job_application_id": job_application.pk}))

    # Check optgroup labels
    job_description = JobDescriptionFactory(siae=job_application.to_siae, is_active=True)
    response = client.get(reverse("apply:accept", kwargs={"job_application_id": job_application.pk}))
    assert response.status_code == 200
    assertContains(response, f"{job_description.display_name} - {job_description.display_location}", html=True)
    assertContains(response, ACTIVE_JOBS_LABEL)
    assertNotContains(response, INACTIVE_JOBS_LABEL)
    assertNotContains(response, JOB_DETAILS_LABEL)

    # Inactive job description must also appear in select
    job_description = JobDescriptionFactory(siae=job_application.to_siae, is_active=False)
    response = client.get(reverse("apply:accept", kwargs={"job_application_id": job_application.pk}))
    assert response.status_code == 200
    assertContains(response, f"{job_description.display_name} - {job_description.display_location}", html=True)
    assertContains(response, ACTIVE_JOBS_LABEL)
    assertContains(response, INACTIVE_JOBS_LABEL)
    assertNotContains(response, JOB_DETAILS_LABEL)


def test_select_other_job_description_for_job_application(client):
    create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
    create_test_cities(["54", "57"], num_per_department=2)

    job_application = JobApplicationFactory(
        to_siae__kind=CompanyKind.EI, state=JobApplicationWorkflow.STATE_PROCESSING
    )
    user = job_application.to_siae.members.first()
    JobDescriptionFactory(siae=job_application.to_siae, is_active=True)
    city = City.objects.order_by("?").first()
    url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
    data = {
        "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_FORGOTTEN,
        "lack_of_nir": True,
        "lack_of_nir_reason": LackOfNIRReason.TEMPORARY_NUMBER,
        "address_line_1": "11 rue des Lilas",
        "post_code": "57000",
        "city": city.name,
        "city_slug": city.slug,
    }

    client.force_login(user)
    response = client.get(url)

    assertContains(response, ACTIVE_JOBS_LABEL)
    assertNotContains(response, INACTIVE_JOBS_LABEL)
    assertNotContains(response, JOB_DETAILS_LABEL)

    # Select "Autre": must provide new job detail fields
    response = client.post(url, data={"hired_job": AcceptForm.OTHER_HIRED_JOB})
    assertContains(response, JOB_DETAILS_LABEL)

    # Check form errors
    data |= {"hired_job": AcceptForm.OTHER_HIRED_JOB}

    response = client.post(url, data=data)
    assert response.status_code == 200

    data |= {"location": city.pk}
    response = client.post(url, data=data)
    assert response.status_code == 200

    appellation = Appellation.objects.order_by("?").first()
    data |= {"appellation": appellation.pk}
    response = client.post(url, data=data)
    assert response.status_code == 200

    tomorrow = timezone.localdate() + relativedelta(days=1)
    data |= {"hiring_start_at": f"{tomorrow:%Y-%m-%d}"}
    response = client.post(url, data=data)
    assert response.status_code == 200

    # Modal window
    data |= {"confirmed": True}
    response = client.post(url, data=data, follow=False)
    # Caution: should redirect after that point, but done via HTMX we get a 200 status code
    assert response.status_code == 200
    assert response.url == reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})

    # Perform some checks on job description now attached to job application
    job_application.refresh_from_db()
    assert job_application.hired_job
    assert job_application.hired_job.creation_source == JobDescriptionSource.HIRING
    assert not job_application.hired_job.is_active
    assert job_application.hired_job.description == "La structure n’a pas encore renseigné cette rubrique"


def test_no_job_description_for_job_application(client):
    create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
    job_application = JobApplicationFactory(
        to_siae__kind=CompanyKind.EI, state=JobApplicationWorkflow.STATE_PROCESSING
    )
    user = job_application.to_siae.members.first()

    client.force_login(user)
    response = client.get(reverse("apply:accept", kwargs={"job_application_id": job_application.pk}))

    assertNotContains(response, ACTIVE_JOBS_LABEL)
    assertNotContains(response, INACTIVE_JOBS_LABEL)
    assertNotContains(response, JOB_DETAILS_LABEL)
