from itertools import product
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from itou.approvals.factories import PoleEmploiApprovalFactory, SuspensionFactory
from itou.approvals.models import Approval, Suspension
from itou.cities.factories import create_test_cities
from itou.eligibility.enums import AuthorKind
from itou.eligibility.factories import EligibilityDiagnosisFactory
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.employee_record.enums import Status
from itou.employee_record.factories import EmployeeRecordFactory
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberOrganizationFactory,
)
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeFactory
from itou.users.enums import UserKind
from itou.users.factories import JobSeekerWithAddressFactory, PrescriberFactory
from itou.users.models import User
from itou.utils.templatetags.format_filters import format_nir
from itou.utils.test import TestCase
from itou.utils.widgets import DuetDatePickerWidget


# patch the one used in the `models` module, not the original one in tasks
@patch("itou.job_applications.models.huey_notify_pole_emploi", return_value=False)
class ProcessViewsTest(TestCase):
    def accept_job_application(self, job_application, post_data=None, city=None, assert_successful=True):
        """
        This is not a test. It's a shortcut to process "apply:accept" view steps:
        - GET
        - POST: show the confirmation modal
        - POST: hide the modal and redirect to the next url.
        """
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url_accept)
        assert response.status_code == 200
        self.assertContains(response, "Confirmation de l’embauche")
        # Make sure modal is hidden.
        self.assertNotContains(response, "data-htmx-open-modal")

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
            }

        response = self.client.post(url_accept, HTTP_HX_REQUEST="true", data=post_data)
        if assert_successful:
            self.assertContains(response, "data-htmx-open-modal")
        else:
            self.assertNotContains(response, "data-htmx-open-modal")

        post_data = post_data | {"confirmed": "True"}
        response = self.client.post(url_accept, HTTP_HX_REQUEST="true", data=post_data)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        # django-htmx triggers a client side redirect when it receives a response with the HX-Redirect header.
        # It renders an HttpResponseRedirect subclass which, unfortunately, responds with a 200 status code.
        # I guess it's normal as it's an AJAX response.
        # See https://django-htmx.readthedocs.io/en/latest/http.html#django_htmx.http.HttpResponseClientRedirect # noqa
        if assert_successful:
            self.assertRedirects(response, next_url, status_code=200)
        return response, next_url

    def test_details_for_siae(self, *args, **kwargs):
        """Display the details of a job application."""

        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True, resume_link="")
        siae = job_application.to_siae
        siae_user = siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        assert not job_application.has_editable_job_seeker
        self.assertContains(response, "Ce candidat a pris le contrôle de son compte utilisateur.")
        self.assertContains(response, format_nir(job_application.job_seeker.nir))
        self.assertContains(response, job_application.job_seeker.pole_emploi_id)
        self.assertContains(response, job_application.job_seeker.phone)

        job_application.job_seeker.created_by = siae_user
        job_application.job_seeker.phone = ""
        job_application.job_seeker.nir = ""
        job_application.job_seeker.pole_emploi_id = ""
        job_application.job_seeker.save()

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        assert job_application.has_editable_job_seeker
        self.assertContains(response, "Modifier les informations")
        self.assertContains(response, "Adresse : <span>Non renseignée</span>", html=True)
        self.assertContains(response, "Téléphone : <span>Non renseigné</span>", html=True)
        self.assertContains(response, "CV : <span>Non renseigné</span>", html=True)
        self.assertContains(response, "Identifiant Pôle emploi : <span>Non renseigné</span>", html=True)
        self.assertContains(response, "Numéro de sécurité sociale : <span>Non renseigné</span>", html=True)

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
        resume_link = "https://server.com/rockie-balboa.pdf"
        job_application = JobApplicationSentByJobSeekerFactory(to_siae=siae)
        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertContains(response, resume_link)

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

        job_application = JobApplicationFactory(with_approval=True, resume_link="")
        prescriber = job_application.sender_prescriber_organization.members.first()

        self.client.force_login(prescriber)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        # Job seeker nir is displayed
        self.assertContains(response, format_nir(job_application.job_seeker.nir))
        # Approval is displayed
        self.assertContains(response, "PASS IAE (agrément) disponible")

        self.assertContains(response, "Adresse : <span>Non renseignée</span>", html=True)
        self.assertContains(response, "CV : <span>Non renseigné</span>", html=True)

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

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        assert job_application.state.is_processing
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

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        assert job_application.state.is_processing
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
        cities = create_test_cities(["54", "57"], num_per_department=2)
        city = cities[0]
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

        hiring_end_dates = [
            Approval.get_default_end_date(today),
            None,
        ]
        cases = list(product(hiring_end_dates, JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES))

        for hiring_end_at, state in cases:
            with self.subTest(hiring_end_at=hiring_end_at, state=state):
                job_application = JobApplicationSentByJobSeekerFactory(
                    state=state, job_seeker=job_seeker, to_siae=siae
                )
                self.client.force_login(siae_user)
                previous_last_checked_at = job_seeker.last_checked_at

                # Good duration.
                hiring_start_at = today
                post_data = {
                    # Data for `JobSeekerPoleEmploiStatusForm`.
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
                assert response.status_code == 200
                # test case hiring_end_at
                if hiring_end_at:
                    self.assertContains(response, f"Fin : {hiring_end_at.strftime('%d')}")
                else:
                    self.assertContains(response, "Fin : Non renseigné")
                # last_checked_at has been updated
                assert job_application.job_seeker.last_checked_at > previous_last_checked_at

        ##############
        # Exceptions #
        ##############
        job_application = JobApplicationSentByJobSeekerFactory(state=state, job_seeker=job_seeker, to_siae=siae)

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
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, to_siae=siae
        )

        hiring_start_at = today
        hiring_end_at = Approval.get_default_end_date(hiring_start_at)
        post_data = {
            # Data for `JobSeekerPoleEmploiStatusForm`.
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

    def test_accept_with_active_suspension(self, *args, **kwargs):
        """Test the `accept` transition with active suspension for active user"""
        cities = create_test_cities(["54", "57"], num_per_department=2)
        city = cities[0]
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
        job_application = JobApplicationSentByJobSeekerFactory(
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
            # Data for `JobSeekerPoleEmploiStatusForm`.
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
        [city] = create_test_cities(["57"], num_per_department=1)

        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            # The state of the 3 `pole_emploi_*` fields will trigger a manual delivery.
            job_seeker__nir="",
            job_seeker__pole_emploi_id="",
            job_seeker__lack_of_pole_emploi_id_reason=User.REASON_FORGOTTEN,
        )

        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        post_data = {
            # Data for `JobSeekerPoleEmploiStatusForm`.
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

        self.accept_job_application(job_application=job_application, post_data=post_data)
        job_application.refresh_from_db()
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_MANUAL

    def test_accept_and_update_hiring_start_date_of_two_job_applications(self, *args, **kwargs):
        cities = create_test_cities(["54", "57"], num_per_department=2)
        city = cities[0]
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
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_app_starting_earlier = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_app_starting_later = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_PROCESSING
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
        cities = create_test_cities(["54"], num_per_department=1)
        city = cities[0]

        siae = SiaeFactory(with_membership=True)
        job_seeker = JobSeekerWithAddressFactory(city=city.name)
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, job_seeker=job_seeker, to_siae=siae
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
        another_job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, job_seeker=almost_same_job_seeker, to_siae=siae
        )

        # Gracefully display a message instead of just plain crashing
        _, next_url = self.accept_job_application(job_application=another_job_application, city=city)
        response = self.client.get(next_url)
        assert "Un PASS IAE lui a déjà été délivré mais il est associé à un autre compte. " in str(
            list(response.context["messages"])[0]
        )

    def test_eligibility(self, *args, **kwargs):
        """Test eligibility."""
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            job_seeker=JobSeekerWithAddressFactory(with_address_in_qpv=True),
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

        # Ensure that a manual confirmation is mandatory.
        post_data = {"confirm": "false"}
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200

        post_data = {
            # Administrative criteria level 1.
            f"{criterion1.key}": "true",
            # Administrative criteria level 2.
            f"{criterion2.key}": "true",
            f"{criterion3.key}": "true",
            # Confirm.
            "confirm": "true",
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
        assert eligibility_diagnosis.author_kind == AuthorKind.SIAE_STAFF
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
            to_siae__kind=SiaeKind.GEIQ,
        )
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        assert response.status_code == 404

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
        job_application = JobApplicationFactory(with_approval=True)
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)
        url = reverse("apply:cancel", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        self.assertContains(response, "Confirmer l'annulation de l'embauche")
        self.assertContains(
            response, "En validant, <b>vous renoncez aux aides au poste</b> liées à cette candidature pour tous"
        )

        post_data = {
            "confirm": "true",
        }
        response = self.client.post(url, data=post_data)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        self.assertRedirects(response, next_url)

        job_application.refresh_from_db()
        assert job_application.state.is_cancelled

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
        cities = create_test_cities(["54", "57"], num_per_department=2)
        city = cities[0]
        job_seeker = JobSeekerWithAddressFactory(city=city.name)
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_CANCELLED, job_seeker=job_seeker
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

        args = {"states": [c for c in cancelled_states]}
        qs = urlencode(args, doseq=True)
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
        cls.job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
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
        self.assertNotContains(response, self.url_refuse)
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


class ProcessTransferJobApplicationTest(TestCase):

    TRANSFER_TO_OTHER_SIAE_SENTENCE = "Transférer vers une autre structure"

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

        assert 2 == user.siaemembership_set.count()

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
        other_siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        other_siae.members.add(user)
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            to_siae=siae,
            state=JobApplicationWorkflow.STATE_PROCESSING,
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
        assert f"transférée à la SIAE <b>{other_siae.display_name}</b>" in str(messages[0])
