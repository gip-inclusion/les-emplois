from unittest.mock import PropertyMock, patch

from dateutil.relativedelta import relativedelta
from django.contrib.messages import get_messages
from django.core import mail
from django.core.exceptions import ObjectDoesNotExist
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory, SuspensionFactory
from itou.approvals.models import Approval, Prolongation, Suspension
from itou.eligibility.factories import EligibilityDiagnosisFactory
from itou.job_applications.factories import JobApplicationFactory, JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.prescribers.factories import AuthorizedPrescriberOrganizationWithMembershipFactory
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory
from itou.users.models import User
from itou.www.approvals_views.forms import DeclareProlongationForm

from .pdfshift_mock import BITES_FILE


@patch.object(JobApplication, "can_be_cancelled", new_callable=PropertyMock, return_value=False)
class TestDownloadApprovalAsPDF(TestCase):
    @patch("itou.utils.pdf.HtmlToPdf.html_to_bytes", return_value=BITES_FILE)
    def test_download_job_app_approval_as_pdf(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory()
        siae_member = job_application.to_siae.members.first()
        job_seeker = job_application.job_seeker
        EligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        response = self.client.get(
            reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("pdf", response.get("Content-Type"))

    def test_impossible_download_when_approval_is_missing(self, *args, **kwargs):
        """
        The button to download an approval is show only when
        certain conditions are met.
        Nevertheless, don't trust the client. Make sure we raise an error
        if the same conditions are not met in this view.
        """
        # Create a job application without an approval.
        job_application = JobApplicationFactory()
        siae_member = job_application.to_siae.members.first()
        job_seeker = job_application.job_seeker
        EligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)
        response = self.client.get(
            reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
        )
        self.assertEqual(response.status_code, 404)

    @patch("itou.utils.pdf.HtmlToPdf.html_to_bytes", return_value=BITES_FILE)
    @patch("itou.approvals.models.CommonApprovalMixin.originates_from_itou", False)
    def test_download_approval_even_if_diagnosis_is_missing(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory()
        siae_member = job_application.to_siae.members.first()

        # An approval has been delivered but it does not come from Itou.
        # Therefore, the linked diagnosis exists but is not in our database.
        # Don't create a diagnosis.
        # EligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        response = self.client.get(
            reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("pdf", response.get("Content-Type"))

    @patch("itou.approvals.models.CommonApprovalMixin.originates_from_itou", True)
    def test_no_download_if_missing_diagnosis(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory()
        siae_member = job_application.to_siae.members.first()

        # An approval has been delivered by Itou but there is no diagnosis.
        # It should raise an error.
        # EligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        with self.assertRaises(ObjectDoesNotExist):
            self.client.get(reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk}))


class ApprovalSuspendViewTest(TestCase):
    def test_suspend_approval(self):
        """
        Test the creation of a suspension.
        """

        today = timezone.now().date()

        job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today
            - relativedelta(days=JobApplication.CANCELLATION_DAYS_AFTER_HIRING_STARTED)
            - relativedelta(days=1),
        )

        approval = job_application.approval
        self.assertEqual(0, approval.suspension_set.count())

        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        back_url = "/"
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspend", kwargs={"approval_id": approval.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preview"], False)

        start_at = today
        end_at = today + relativedelta(days=10)

        post_data = {
            "start_at": start_at.strftime("%d/%m/%Y"),
            "end_at": end_at.strftime("%d/%m/%Y"),
            "reason": Suspension.Reason.SICKNESS,
            "reason_explanation": "",
            # Preview.
            "preview": "1",
        }

        # Go to preview.
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preview"], True)

        # Save to DB.
        del post_data["preview"]
        post_data["save"] = 1

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, back_url)

        self.assertEqual(1, approval.suspension_set.count())
        suspension = approval.suspension_set.first()
        self.assertEqual(suspension.created_by, siae_user)

    def test_update_suspension(self):
        """
        Test the update of a suspension.
        """

        today = timezone.now().date()

        job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today
            - relativedelta(days=JobApplication.CANCELLATION_DAYS_AFTER_HIRING_STARTED)
            - relativedelta(days=1),
        )

        approval = job_application.approval
        siae_user = job_application.to_siae.members.first()
        start_at = today
        end_at = today + relativedelta(days=10)

        suspension = SuspensionFactory(approval=approval, start_at=start_at, end_at=end_at, created_by=siae_user)

        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        back_url = "/"
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspension_update", kwargs={"suspension_id": suspension.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        new_end_at = end_at + relativedelta(days=30)

        post_data = {
            "start_at": suspension.start_at.strftime("%d/%m/%Y"),
            "end_at": new_end_at.strftime("%d/%m/%Y"),
            "reason": suspension.reason,
            "reason_explanation": suspension.reason_explanation,
        }

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, back_url)

        self.assertEqual(1, approval.suspension_set.count())
        suspension = approval.suspension_set.first()
        self.assertEqual(suspension.updated_by, siae_user)
        self.assertEqual(suspension.end_at, new_end_at)

    def test_delete_suspension(self):
        """
        Test the deletion of a suspension.
        """

        today = timezone.now().date()

        job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today
            - relativedelta(days=JobApplication.CANCELLATION_DAYS_AFTER_HIRING_STARTED)
            - relativedelta(days=1),
        )

        approval = job_application.approval
        siae_user = job_application.to_siae.members.first()
        start_at = today
        end_at = today + relativedelta(days=10)

        suspension = SuspensionFactory(approval=approval, start_at=start_at, end_at=end_at, created_by=siae_user)

        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        back_url = "/"
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspension_delete", kwargs={"suspension_id": suspension.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {"confirm": "true"}

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, back_url)

        self.assertEqual(0, approval.suspension_set.count())


class ApprovalProlongationTest(TestCase):
    def setUp(self):
        """
        Create test objects.
        """

        self.prescriber_organization = AuthorizedPrescriberOrganizationWithMembershipFactory()
        self.prescriber = self.prescriber_organization.members.first()

        today = timezone.now().date()

        # Set "now" to be "after" the day approval is open to prolongation.
        approval_end_at = (
            today
            + relativedelta(months=Approval.PROLONGATION_PERIOD_BEFORE_APPROVAL_END_MONTHS)
            - relativedelta(days=1)
        )
        self.job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today
            - relativedelta(days=JobApplication.CANCELLATION_DAYS_AFTER_HIRING_STARTED)
            - relativedelta(days=1),
            approval__end_at=approval_end_at,
        )
        self.siae = self.job_application.to_siae
        self.siae_user = self.job_application.to_siae.members.first()
        self.approval = self.job_application.approval
        self.assertEqual(0, self.approval.prolongation_set.count())

    def test_form_without_pre_existing_instance(self):
        """
        Test the default state of `DeclareProlongationForm`.
        """
        form = DeclareProlongationForm(approval=self.approval, siae=self.siae, data={})

        self.assertIsNone(form.fields["reason"].initial)

        # Ensure that `form.instance` is populated so that `Prolongation.clean()`
        # is triggered from within the form validation step with the right data.
        self.assertEqual(form.instance.declared_by_siae, self.siae)
        self.assertEqual(form.instance.approval, self.approval)
        self.assertEqual(form.instance.start_at, Prolongation.get_start_at(self.approval))

    def test_prolong_approval_view(self):
        """
        Test the creation of a prolongation.
        """

        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)

        back_url = "/"
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preview"], False)

        reason = Prolongation.Reason.SENIOR
        end_at = Prolongation.get_max_end_at(self.approval.end_at, reason=reason)

        post_data = {
            "end_at": end_at.strftime("%d/%m/%Y"),
            "reason": reason,
            "reason_explanation": "Reason explanation is required.",
            "email": self.prescriber.email,
            # Preview.
            "preview": "1",
        }

        # Go to preview.
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preview"], True)

        # Save to DB.
        del post_data["preview"]
        post_data["save"] = 1

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, back_url)

        self.assertEqual(1, self.approval.prolongation_set.count())

        prolongation = self.approval.prolongation_set.first()
        self.assertEqual(prolongation.created_by, self.siae_user)
        self.assertEqual(prolongation.declared_by, self.siae_user)
        self.assertEqual(prolongation.declared_by_siae, self.job_application.to_siae)
        self.assertEqual(prolongation.validated_by, self.prescriber)
        self.assertEqual(prolongation.reason, post_data["reason"])

        # An email should have been sent to the chosen authorized prescriber.
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(len(email.to), 1)
        self.assertEqual(email.to[0], post_data["email"])


class PoleEmploiApprovalConversionIntoApprovalTest(TestCase):
    def setUp(self):
        """
        Create test objects.
        """
        self.job_application = JobApplicationWithApprovalFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        self.siae = self.job_application.to_siae
        self.siae_user = self.job_application.to_siae.members.first()
        self.approval = self.job_application.approval
        self.job_seeker = self.job_application.job_seeker
        self.pe_approval = PoleEmploiApprovalFactory()

    def test_pe_approval_search_view_default(self):
        """
        The search for PE approval screen should not crash ;)
        """

        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse("approvals:pe_approval_search")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rechercher un agrément Pôle emploi")

    def test_pe_approval_search_view_nominal(self):
        """
        The search for PE approval screen should display the job seeker's name
        if the PE approval number that was searched for has a matching PE approval
        """

        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        params = urlencode({"number": self.pe_approval.number})
        url = reverse("approvals:pe_approval_search")
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Agrément trouvé")

    def test_pe_approval_search_view_no_results(self):
        """
        The search for PE approval screen should display that there is no results
        if a PE approval number was searched for but nothing was found
        """

        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        params = urlencode({"number": 123})
        url = reverse("approvals:pe_approval_search")
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nous n'avons pas trouvé d'agrément")

    def test_pe_approval_search_view_has_matching_pass_iae(self):
        """
        The search for PE approval screen should redirect to the matching job application details screen if the
        number matches a PASS IAE attached to a job_application
        """
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)

        params = urlencode({"number": self.approval.number})
        url = reverse("approvals:pe_approval_search")
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": self.job_application.id})
        self.assertEqual(response.url, next_url)

    def test_pe_approval_search_view_unlogged_is_not_authorized(self):
        """
        It is not possible to access the search for PE approval screen unlogged
        """
        url = reverse("approvals:pe_approval_search")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        next_url = reverse("account_login")
        self.assertIn(next_url, response.url)

    def test_pe_approval_search_view_as_job_seeker_is_not_authorized(self):
        """
        The search for PE approval screen as job seeker is not authorized
        """
        self.client.login(username=self.job_seeker.email, password=DEFAULT_PASSWORD)

        url = reverse("approvals:pe_approval_search")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_pe_approval_search_user_nominal(self):
        """
        The search for PE approval screen should redirect to the matching job application details screen if the
        number matches a PASS IAE attached to a job_application
        """
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse("approvals:pe_approval_search_user", kwargs={"pe_approval_id": self.pe_approval.id})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.pe_approval.last_name)
        self.assertContains(response, self.pe_approval.first_name)

    def test_pe_approval_search_user_invalid_pe_approval(self):
        """
        The search for PE approval screen should redirect to the matching job application details screen if the
        number matches a PASS IAE attached to a job_application
        """
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse("approvals:pe_approval_search_user", kwargs={"pe_approval_id": 123})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_pe_approval_create_from_new_user(self):
        """
        When the user does not exist for the suggested email, it is created as well as the approval
        """
        initial_approval_count = Approval.objects.count()
        initial_user_count = User.objects.count()
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        email = "some.new@email.com"
        url = reverse("approvals:pe_approval_create", kwargs={"pe_approval_id": self.pe_approval.id})
        params = {"email": email}
        response = self.client.post(url, params)

        new_user = User.objects.get(email=email)

        self.assertTrue(new_user.approvals_wrapper.has_valid)
        self.assertEqual(new_user.approvals_wrapper.latest_approval.number, self.pe_approval.number[:12])
        self.assertEqual(response.status_code, 302)
        self.assertTrue(new_user.last_accepted_job_application is not None)
        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": new_user.last_accepted_job_application.id}
        )
        self.assertEqual(response.url, next_url)
        self.assertEqual(Approval.objects.count(), initial_approval_count + 1)
        self.assertEqual(User.objects.count(), initial_user_count + 1)

    def test_pe_approval_create_from_existing_user_without_approval(self):
        """
        When an existing user has no valid approval, it is possible to import a Pole Emploi Approval
        """
        initial_approval_count = Approval.objects.count()
        job_seeker = JobSeekerFactory()
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse("approvals:pe_approval_create", kwargs={"pe_approval_id": self.pe_approval.id})
        params = {"email": job_seeker.email}
        response = self.client.post(url, params)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Approval.objects.count(), initial_approval_count + 1)
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertEqual(
            str(messages[0]),
            "L'agrément Pole Emploi a bien été importé, vous pouvez désormais le prolonger ou le suspendre.",
        )

    def test_pe_approval_create_when_pole_emploi_approval_has_already_been_imported(self):
        """
        When the PoleEmploiApproval has already been imported, we are redirected to its page
        """
        self.job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED, approval=ApprovalFactory(number=self.pe_approval.number[:12])
        )

        initial_approval_count = Approval.objects.count()
        job_seeker = JobSeekerFactory()
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse("approvals:pe_approval_create", kwargs={"pe_approval_id": self.pe_approval.id})
        params = {"email": job_seeker.email}
        response = self.client.post(url, params)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Approval.objects.count(), initial_approval_count)
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Cet agrément Pole Emploi a déja été importé.")

    def test_pe_approval_create_from_existing_user_with_approval(self):
        """
        When an existing user already has a valid approval, it is not possible to import a Pole Emploi Approval
        """
        self.assertTrue(self.job_seeker.approvals_wrapper.has_valid)

        initial_approval_count = Approval.objects.count()
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse("approvals:pe_approval_create", kwargs={"pe_approval_id": self.pe_approval.id})
        params = {"email": self.job_seeker.email}

        response = self.client.post(url, params)

        self.assertEqual(Approval.objects.count(), initial_approval_count)
        self.assertEqual(response.status_code, 302)
        next_url = reverse("approvals:pe_approval_search_user", kwargs={"pe_approval_id": self.pe_approval.id})
        self.assertEqual(response.url, next_url)
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Le candidat associé à cette adresse email a déja un PASS IAE valide.")
