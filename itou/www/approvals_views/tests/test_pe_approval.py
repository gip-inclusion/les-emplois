from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from itou.approvals.models import Approval
from itou.job_applications.factories import JobApplicationFactory
from itou.job_applications.models import JobApplicationWorkflow
from itou.siaes.factories import SiaeFactory, SiaeMembershipFactory
from itou.users.factories import JobSeekerFactory
from itou.users.models import User


class PoleEmploiApprovalSearchTest(TestCase):
    def setUp(self):
        self.url = reverse("approvals:pe_approval_search")

    def set_up_pe_approval(self, with_job_application=True):
        # pylint: disable=attribute-defined-outside-init
        self.pe_approval = PoleEmploiApprovalFactory()

        self.siae = SiaeFactory(with_membership=True)
        self.siae_user = self.siae.members.first()
        if with_job_application:
            self.job_application = JobApplicationFactory(
                with_approval=True,
                to_siae=self.siae,
                approval__number=self.pe_approval.number,
            )
            self.approval = self.job_application.approval
            self.job_seeker = self.job_application.job_seeker
        else:
            self.approval = None
            self.job_seeker = None

    def test_default(self):
        """
        The search for PE approval screen should not crash ;)
        """
        siae = SiaeMembershipFactory()
        self.client.force_login(siae.user)

        response = self.client.get(self.url)
        self.assertContains(response, "Rechercher")

    def test_nominal(self):
        """
        The search for PE approval screen should be successful
        if the PE approval number that was searched for has a matching PE approval
        but not PASS IAE.
        """
        self.set_up_pe_approval(with_job_application=False)
        self.client.force_login(self.siae_user)

        response = self.client.get(self.url, {"number": self.pe_approval.number})
        self.assertContains(response, "Continuer")

    def test_number_length(self):
        """
        Don't accept approval suffixes (example: 1234567890123P01).
        """
        siae = SiaeMembershipFactory()
        self.client.force_login(siae.user)

        response = self.client.get(self.url, {"number": "1234567890123P01"})
        self.assertFalse(response.context["form"].is_valid())

    def test_no_results(self):
        """
        The search for PE approval screen should display that there is no results
        if a PE approval number was searched for but nothing was found
        """
        siae = SiaeMembershipFactory()
        self.client.force_login(siae.user)

        response = self.client.get(self.url, {"number": 123123123123})
        self.assertNotContains(response, "Continuer")

    def test_has_matching_pass_iae(self):
        """
        The search for PE approval screen should redirect to the matching job application details screen if the
        number matches a PASS IAE attached to a job_application
        """
        self.set_up_pe_approval()

        self.client.force_login(self.siae_user)

        response = self.client.get(self.url, {"number": self.approval.number})
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": self.job_application.id})
        self.assertEqual(response.url, next_url)

    def test_has_no_last_accepted_job_application(self):
        """
        In some cases, there is an approval but no matching accepted job application
        """
        self.set_up_pe_approval(with_job_application=True)
        ja = self.job_seeker.job_applications.first()
        ja.state = JobApplicationWorkflow.STATE_CANCELLED
        ja.save()

        self.client.force_login(self.siae_user)
        # Our approval should not be usable without a job application
        response = self.client.get(self.url, {"number": self.approval.number})
        self.assertNotContains(response, "Continuer")

    def test_has_matching_pass_iae_that_belongs_to_another_siae(self):
        """
        Make sure to NOT to redirect to job applications belonging to other SIAEs,
        as this would produce a 404.
        """

        # Initial approvals (PE and PASS)
        self.set_up_pe_approval()

        # Create a job application with a PASS IAE created from a `PoleEmploiApproval`
        # that belongs to another siae.
        job_seeker = JobSeekerFactory()
        pe_approval = PoleEmploiApprovalFactory()
        job_application = JobApplicationFactory(
            with_approval=True,
            approval__number=pe_approval.number,
            approval__user=job_seeker,
            job_seeker=job_seeker,
        )

        another_siae = job_application.to_siae
        self.assertNotEqual(another_siae, self.siae)

        # This is the current user (NOT a member of `another_siae`).
        self.client.force_login(self.siae_user)

        # The current user should not be able to use the PASS IAE used by another SIAE.
        response = self.client.get(self.url, {"number": job_application.approval.number})
        self.assertNotContains(response, "Continuer")

    def test_unlogged_is_not_authorized(self):
        """
        It is not possible to access the search for PE approval screen unlogged
        """

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        # TODO: (cms) redirect to prescriber's connection page with a flash message instead.
        # AssertionError: '/login/job_seeker' not found in '/accounts/login/?next=/approvals/pe-approval/search'
        next_url = reverse("account_login")
        self.assertIn(next_url, response.url)

    def test_as_job_seeker_is_not_authorized(self):
        """
        The search for PE approval screen as job seeker is not authorized
        """
        job_application = JobApplicationFactory(with_approval=True)
        self.client.force_login(job_application.job_seeker)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)


class PoleEmploiApprovalSearchUserTest(TestCase):
    def setUp(self):
        self.job_application = JobApplicationFactory(with_approval=True)
        self.siae = self.job_application.to_siae
        self.siae_user = self.job_application.to_siae.members.first()
        self.approval = self.job_application.approval
        self.pe_approval = PoleEmploiApprovalFactory()

    def test_nominal(self):
        """
        The search for PE approval screen should redirect to the matching job application details screen if the
        number matches a PASS IAE attached to a job_application
        """
        self.client.force_login(self.siae_user)

        url = reverse("approvals:pe_approval_search_user", kwargs={"pe_approval_id": self.pe_approval.id})

        response = self.client.get(url)
        self.assertContains(response, self.pe_approval.last_name.title())
        self.assertContains(response, self.pe_approval.first_name.title())

    def test_invalid_pe_approval(self):
        """
        The search for PE approval screen should redirect to the matching job application details screen if the
        number matches a PASS IAE attached to a job_application
        """
        self.client.force_login(self.siae_user)

        url = reverse("approvals:pe_approval_search_user", kwargs={"pe_approval_id": 123})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class PoleEmploiApprovalCreateTest(TestCase):
    def setUp(self):
        self.job_application = JobApplicationFactory(with_approval=True)
        self.siae = self.job_application.to_siae
        self.siae_user = self.job_application.to_siae.members.first()
        self.approval = self.job_application.approval
        self.job_seeker = self.job_application.job_seeker
        self.pe_approval = PoleEmploiApprovalFactory()

    def test_from_new_user(self):
        """
        When the user does not exist for the suggested email, it is created as well as the approval
        """
        initial_approval_count = Approval.objects.count()
        initial_user_count = User.objects.count()
        self.client.force_login(self.siae_user)
        email = "some.new@email.com"
        url = reverse("approvals:pe_approval_create", kwargs={"pe_approval_id": self.pe_approval.id})
        params = {"email": email}
        response = self.client.post(url, params)

        new_user = User.objects.get(email=email)

        self.assertTrue(new_user.has_valid_common_approval)
        self.assertEqual(new_user.latest_approval.number, self.pe_approval.number)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(new_user.last_accepted_job_application is not None)
        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": new_user.last_accepted_job_application.id}
        )
        self.assertEqual(response.url, next_url)
        self.assertEqual(Approval.objects.count(), initial_approval_count + 1)
        self.assertEqual(User.objects.count(), initial_user_count + 1)

    def test_from_existing_user_without_approval(self):
        """
        When an existing user has no valid approval, it is possible to import a Pôle emploi Approval
        """
        initial_approval_count = Approval.objects.count()
        job_seeker = JobSeekerFactory()
        self.client.force_login(self.siae_user)

        url = reverse("approvals:pe_approval_create", kwargs={"pe_approval_id": self.pe_approval.id})
        params = {"email": job_seeker.email}
        response = self.client.post(url, params)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Approval.objects.count(), initial_approval_count + 1)
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(
            messages[-1].message,
            "L'agrément a bien été importé, vous pouvez désormais le prolonger ou le suspendre.",
        )

    def test_when_pole_emploi_approval_has_already_been_imported(self):
        """
        When the PoleEmploiApproval has already been imported, we are redirected to its page
        """
        self.job_application = JobApplicationFactory(
            with_approval=True,
            approval=ApprovalFactory(number=self.pe_approval.number[:12]),
        )

        initial_approval_count = Approval.objects.count()
        job_seeker = JobSeekerFactory()
        self.client.force_login(self.siae_user)

        url = reverse("approvals:pe_approval_create", kwargs={"pe_approval_id": self.pe_approval.id})
        params = {"email": job_seeker.email}
        response = self.client.post(url, params)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Approval.objects.count(), initial_approval_count)
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(messages[-1].message, "Cet agrément a déjà été importé.")

    def test_from_existing_user_with_approval(self):
        """
        When an existing user already has a valid approval, it is not possible to import a Pole Emploi Approval
        """
        self.assertTrue(self.job_seeker.has_valid_common_approval)

        initial_approval_count = Approval.objects.count()
        self.client.force_login(self.siae_user)

        url = reverse("approvals:pe_approval_create", kwargs={"pe_approval_id": self.pe_approval.id})
        params = {"email": self.job_seeker.email}

        response = self.client.post(url, params)

        self.assertEqual(Approval.objects.count(), initial_approval_count)
        self.assertEqual(response.status_code, 302)
        next_url = reverse("approvals:pe_approval_search_user", kwargs={"pe_approval_id": self.pe_approval.id})
        self.assertEqual(response.url, next_url)
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(messages[-1].message, "Le candidat associé à cette adresse e-mail a déjà un PASS IAE valide.")
