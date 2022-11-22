from itertools import product
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from itou.approvals.factories import PoleEmploiApprovalFactory, SuspensionFactory
from itou.approvals.models import Approval, Suspension
from itou.cities.factories import create_test_cities
from itou.cities.models import City
from itou.eligibility.factories import EligibilityDiagnosisFactory
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.employee_record.enums import Status
from itou.employee_record.factories import EmployeeRecordFactory
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.factories import JobApplicationFactory, JobApplicationSentByJobSeekerFactory
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeFactory
from itou.users.factories import JobSeekerWithAddressFactory
from itou.users.models import User
from itou.utils.templatetags.format_filters import format_nir
from itou.utils.test import TestCase
from itou.utils.widgets import DuetDatePickerWidget


# patch the one used in the `models` module, not the original one in tasks
@patch("itou.job_applications.models.huey_notify_pole_emploi", return_value=False)
class ProcessViewsTest(TestCase):
    """Application process"""

    def test_details_for_siae(self, *args, **kwargs):
        """Display the details of a job application."""

        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        siae = job_application.to_siae
        siae_user = siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertFalse(job_application.has_editable_job_seeker)
        self.assertContains(response, "Ce candidat a pris le contrôle de son compte utilisateur.")
        self.assertContains(response, format_nir(job_application.job_seeker.nir))

        job_application.job_seeker.created_by = siae_user
        job_application.job_seeker.save()

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertTrue(job_application.has_editable_job_seeker)
        self.assertContains(response, "Modifier les informations")

        # Test resume presence:
        # 1/ Job seeker has a personal resume (technical debt).
        resume_link = "https://server.com/rockie-balboa.pdf"
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker__resume_link=resume_link, resume_link="", to_siae=siae
        )
        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
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
            sent_by_authorized_prescriber_organisation=True, job_seeker__is_job_seeker=True, hidden_for_siae=True
        )
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(404, response.status_code)

    def test_details_for_siae_as_prescriber(self, *args, **kwargs):
        """As a prescriber, I cannot access the job_applications details for SIAEs."""

        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        prescriber = job_application.sender_prescriber_organization.members.first()

        self.client.force_login(prescriber)

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_details_for_prescriber(self, *args, **kwargs):
        """As a prescriber, I can access the job_applications details for prescribers."""

        job_application = JobApplicationFactory(with_approval=True)
        prescriber = job_application.sender_prescriber_organization.members.first()

        self.client.force_login(prescriber)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Job seeker nir is displayed
        self.assertContains(response, format_nir(job_application.job_seeker.nir))
        # Approval is displayed
        self.assertContains(response, "PASS IAE (agrément) disponible")

    def test_details_for_prescriber_as_siae(self, *args, **kwargs):
        """As a SIAE user, I cannot access the job_applications details for prescribers."""

        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

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
        self.assertTrue(job_application.state.is_processing)

    def test_refuse(self, *args, **kwargs):
        """Ensure that the `refuse` transition is triggered."""

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        self.assertTrue(job_application.state.is_processing)
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:refuse", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "refusal_reason": job_applications_enums.RefusalReason.OTHER,
            "answer": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        self.assertRedirects(response, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        self.assertTrue(job_application.state.is_refused)

    def test_postpone(self, *args, **kwargs):
        """Ensure that the `postpone` transition is triggered."""

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        self.assertTrue(job_application.state.is_processing)
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:postpone", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {"answer": ""}
        response = self.client.post(url, data=post_data)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        self.assertRedirects(response, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        self.assertTrue(job_application.state.is_postponed)

    def test_accept(self, *args, **kwargs):
        create_test_cities(["54", "57"], num_per_department=2)
        city = City.objects.first()
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

                url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Confirmation de l’embauche")

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

                response = self.client.post(url, data=post_data)
                next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
                self.assertRedirects(response, next_url)

                job_application = JobApplication.objects.get(pk=job_application.pk)
                self.assertEqual(job_application.hiring_start_at, hiring_start_at)
                self.assertEqual(job_application.hiring_end_at, hiring_end_at)
                self.assertTrue(job_application.state.is_accepted)

                # test how hiring_end_date is displayed
                response = self.client.get(next_url)
                self.assertEqual(response.status_code, 200)
                # test case hiring_end_at
                if hiring_end_at:
                    self.assertContains(response, f"Fin : {hiring_end_at.strftime('%d')}")
                else:
                    self.assertContains(response, "Fin : Non renseigné")

        ##############
        # Exceptions #
        ##############
        job_application = JobApplicationSentByJobSeekerFactory(state=state, job_seeker=job_seeker, to_siae=siae)
        url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

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
        response = self.client.post(url, data=post_data)
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
        response = self.client.post(url, data=post_data)
        self.assertFormError(response.context["form_accept"], None, JobApplication.ERROR_END_IS_BEFORE_START)

        # No address provided.
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, to_siae=siae
        )
        url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

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
        response = self.client.post(url, data=post_data)
        self.assertFormError(response.context["form_user_address"], "address_line_1", "Ce champ est obligatoire.")
        self.assertFormError(response.context["form_user_address"], "city", "Ce champ est obligatoire.")
        self.assertFormError(response.context["form_user_address"], "post_code", "Ce champ est obligatoire.")

    def test_accept_with_active_suspension(self, *args, **kwargs):
        """Test the `accept` transition with active suspension for active user"""
        create_test_cities(["54", "57"], num_per_department=2)
        city = City.objects.first()
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
        url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

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
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        get_job_application = JobApplication.objects.get(pk=job_application.pk)
        g_suspension = get_job_application.approval.suspension_set.in_progress().last()

        # The end date of suspension is set to d-1 of hiring start day
        self.assertEqual(g_suspension.end_at, get_job_application.hiring_start_at - relativedelta(days=1))
        # Check if the duration of approval was updated correctly
        self.assertEqual(
            get_job_application.approval.end_at,
            approval_job_seeker.end_at + relativedelta(days=(g_suspension.end_at - g_suspension.start_at).days),
        )

    def test_accept_with_manual_approval_delivery(self, *args, **kwargs):
        """
        Test the "manual approval delivery mode" path of the view.
        """
        create_test_cities(["57"], num_per_department=1)
        city = City.objects.first()

        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            # The state of the 3 `pole_emploi_*` fields will trigger a manual delivery.
            job_seeker__nir="",
            job_seeker__pole_emploi_id="",
            job_seeker__lack_of_pole_emploi_id_reason=User.REASON_FORGOTTEN,
        )

        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

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
        response = self.client.post(url, data=post_data)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        self.assertRedirects(response, next_url)

        job_application.refresh_from_db()
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_MANUAL)

    def test_accept_and_update_hiring_start_date_of_two_job_applications(self, *args, **kwargs):
        create_test_cities(["54", "57"], num_per_department=2)
        city = City.objects.first()
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
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            **base_for_post_data,
        }
        response = self.client.post(url_accept, data=post_data)
        self.assertEqual(response.status_code, 302)

        # First job application has been accepted.
        # All other job applications are obsolete.
        job_application.refresh_from_db()
        self.assertTrue(job_application.state.is_accepted)
        self.assertEqual(job_application.approval.start_at, job_application.hiring_start_at)
        self.assertEqual(job_application.approval.end_at, approval_default_ending)
        self.client.logout()

        # SIAE 2 accepts the second job application
        # but its contract starts earlier than the approval delivered the first time.
        # Approval's starting date should be brought forward.
        user = job_app_starting_earlier.to_siae.members.first()
        hiring_start_at = hiring_start_at - relativedelta(months=1)
        hiring_end_at = hiring_start_at + relativedelta(months=2)
        approval_default_ending = Approval.get_default_end_date(start_at=hiring_start_at)
        job_app_starting_earlier.refresh_from_db()
        self.assertTrue(job_app_starting_earlier.state.is_obsolete)

        self.client.force_login(user)
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_app_starting_earlier.pk})
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            **base_for_post_data,
        }
        response = self.client.post(url_accept, data=post_data)
        job_app_starting_earlier.refresh_from_db()

        # Second job application has been accepted.
        # The job seeker has now two part-time jobs at the same time.
        self.assertEqual(response.status_code, 302)
        self.assertTrue(job_app_starting_earlier.state.is_accepted)
        self.assertEqual(job_app_starting_earlier.approval.start_at, job_app_starting_earlier.hiring_start_at)
        self.assertEqual(job_app_starting_earlier.approval.end_at, approval_default_ending)
        self.client.logout()

        # SIAE 3 accepts the third job application.
        # Its contract starts later than the corresponding approval.
        # Approval's starting date should not be updated.
        user = job_app_starting_later.to_siae.members.first()
        hiring_start_at = hiring_start_at + relativedelta(months=6)
        hiring_end_at = hiring_start_at + relativedelta(months=2)
        job_app_starting_later.refresh_from_db()
        self.assertTrue(job_app_starting_later.state.is_obsolete)

        self.client.force_login(user)
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_app_starting_later.pk})
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            **base_for_post_data,
        }
        response = self.client.post(url_accept, data=post_data)
        job_app_starting_later.refresh_from_db()

        # Third job application has been accepted.
        # The job seeker has now three part-time jobs at the same time.
        self.assertEqual(response.status_code, 302)
        self.assertTrue(job_app_starting_later.state.is_accepted)
        self.assertEqual(job_app_starting_later.approval.start_at, job_app_starting_earlier.hiring_start_at)

    def test_accept_with_double_user(self, *args, **kwargs):
        def accept_job_application(job_application, city):
            today = timezone.localdate()
            return self.client.post(
                reverse("apply:accept", kwargs={"job_application_id": job_application.pk}),
                data={
                    "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
                    "hiring_start_at": today.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                    "hiring_end_at": Approval.get_default_end_date(today).strftime(
                        DuetDatePickerWidget.INPUT_DATE_FORMAT
                    ),
                    "answer": "",
                    "address_line_1": job_application.job_seeker.address_line_1,
                    "post_code": job_application.job_seeker.post_code,
                    "city": city.name,
                    "city_slug": city.slug,
                },
                follow=True,
            )

        create_test_cities(["54"], num_per_department=1)
        city = City.objects.first()

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
        response = accept_job_application(job_application, city)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            "Un PASS IAE lui a déjà été délivré mais il est associé à un autre compte. ",
            str(list(response.context["messages"])[0]),
        )

        # This approval is found thanks to the PE Approval number
        approval = Approval.objects.get(number=pole_emploi_approval.number)
        self.assertEqual(approval.user, job_seeker)

        # Now generate a job seeker that is "almost the same"
        almost_same_job_seeker = JobSeekerWithAddressFactory(
            city=city.name, pole_emploi_id=job_seeker.pole_emploi_id, birthdate=job_seeker.birthdate
        )
        another_job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, job_seeker=almost_same_job_seeker, to_siae=siae
        )

        # Gracefully display a message instead of just plain crashing
        response = accept_job_application(another_job_application, city)
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Un PASS IAE lui a déjà été délivré mais il est associé à un autre compte. ",
            str(list(response.context["messages"])[0]),
        )

    def test_eligibility(self, *args, **kwargs):
        """Test eligibility."""

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        self.assertTrue(job_application.state.is_processing)
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_siae
        )
        self.assertFalse(has_considered_valid_diagnoses)

        criterion1 = AdministrativeCriteria.objects.level1().get(pk=1)
        criterion2 = AdministrativeCriteria.objects.level2().get(pk=5)
        criterion3 = AdministrativeCriteria.objects.level2().get(pk=15)

        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Ensure that a manual confirmation is mandatory.
        post_data = {"confirm": "false"}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

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
        self.assertTrue(has_considered_valid_diagnoses)

        # Check diagnosis.
        eligibility_diagnosis = job_application.get_eligibility_diagnosis()
        self.assertEqual(eligibility_diagnosis.author, siae_user)
        self.assertEqual(eligibility_diagnosis.author_kind, EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF)
        self.assertEqual(eligibility_diagnosis.author_siae, job_application.to_siae)
        # Check administrative criteria.
        administrative_criteria = eligibility_diagnosis.administrative_criteria.all()
        self.assertEqual(3, administrative_criteria.count())
        self.assertIn(criterion1, administrative_criteria)
        self.assertIn(criterion2, administrative_criteria)
        self.assertIn(criterion3, administrative_criteria)

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
        self.assertEqual(response.status_code, 404)

    def test_eligibility_state_for_job_application(self, *args, **kwargs):
        """The eligibility diagnosis page must only be accessible
        in JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES states."""
        siae = SiaeFactory(with_membership=True)
        siae_user = siae.members.first()
        job_application = JobApplicationSentByJobSeekerFactory(to_siae=siae)

        # Right states
        for state in JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES:
            job_application.state = state
            job_application.save()
            self.client.force_login(siae_user)
            url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.client.logout()

        # Wrong state
        job_application.state = JobApplicationWorkflow.STATE_ACCEPTED
        job_application.save()
        self.client.force_login(siae_user)
        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        self.client.logout()

    def test_cancel(self, *args, **kwargs):
        # Hiring date is today: cancellation should be possible.
        job_application = JobApplicationFactory(with_approval=True)
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)
        url = reverse("apply:cancel", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
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
        self.assertTrue(job_application.state.is_cancelled)

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
        self.assertFalse(job_application.state.is_cancelled)

    def test_accept_after_cancel(self, *args, **kwargs):
        # A canceled job application is not linked to an approval
        # unless the job seeker has an accepted job application.
        create_test_cities(["54", "57"], num_per_department=2)
        city = City.objects.first()
        job_seeker = JobSeekerWithAddressFactory(city=city.name)
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_CANCELLED, job_seeker=job_seeker
        )
        siae_user = job_application.to_siae.members.first()
        self.client.force_login(siae_user)

        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        hiring_start_at = timezone.localdate()
        hiring_end_at = Approval.get_default_end_date(hiring_start_at)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
            "answer": "",
            "address_line_1": job_seeker.address_line_1,
            "post_code": job_seeker.post_code,
            "city": city.name,
            "city_slug": city.slug,
        }
        response = self.client.post(url_accept, data=post_data)

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        self.assertRedirects(response, next_url)

        job_application.refresh_from_db()
        self.assertEqual(job_seeker.approvals.count(), 1)
        approval = job_seeker.approvals.first()
        self.assertEqual(approval.start_at, job_application.hiring_start_at)
        self.assertTrue(job_application.state.is_accepted)

    def test_archive(self, *args, **kwargs):
        """Ensure that when an SIAE archives a job_application, the hidden_for_siae flag is updated."""

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, state=JobApplicationWorkflow.STATE_CANCELLED
        )
        self.assertTrue(job_application.state.is_cancelled)
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
        self.assertTrue(job_application.hidden_for_siae)


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

        self.assertEqual(2, user.siaemembership_set.count())

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
        self.assertTrue(messages)
        self.assertEqual(len(messages), 1)
        self.assertIn(f"transférée à la SIAE <b>{other_siae.display_name}</b>", str(messages[0]))
