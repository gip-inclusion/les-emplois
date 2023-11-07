from django.contrib import messages
from django.urls import reverse

from itou.approvals import enums as approvals_enums
from itou.approvals.models import Approval
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.models import JobApplicationWorkflow
from itou.users.models import User
from tests.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import TestCase, assertMessages


class PoleEmploiApprovalSearchTest(TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("approvals:pe_approval_search")

    def set_up_pe_approval(self, with_job_application=True):
        self.pe_approval = PoleEmploiApprovalFactory()

        self.company = CompanyFactory(with_membership=True)
        self.employer = self.company.members.first()
        if with_job_application:
            self.job_application = JobApplicationFactory(
                with_approval=True,
                approval__origin=approvals_enums.Origin.PE_APPROVAL,
                approval__eligibility_diagnosis=None,
                to_company=self.company,
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
        company = CompanyMembershipFactory()
        self.client.force_login(company.user)

        response = self.client.get(self.url)
        self.assertContains(response, "Rechercher")

    def test_nominal(self):
        """
        The search for PE approval screen should be successful
        if the PE approval number that was searched for has a matching PE approval
        but not PASS IAE.
        """
        self.set_up_pe_approval(with_job_application=False)
        self.client.force_login(self.employer)

        response = self.client.get(self.url, {"number": self.pe_approval.number})
        self.assertContains(response, "Continuer")

    def test_number_length(self):
        """
        Don't accept approval suffixes (example: 1234567890123P01).
        """
        company = CompanyMembershipFactory()
        self.client.force_login(company.user)

        response = self.client.get(self.url, {"number": "1234567890123P01"})
        assert not response.context["form"].is_valid()

    def test_no_results(self):
        """
        The search for PE approval screen should display that there is no results
        if a PE approval number was searched for but nothing was found
        """
        company = CompanyMembershipFactory()
        self.client.force_login(company.user)

        response = self.client.get(self.url, {"number": 123123123123})
        self.assertNotContains(response, "Continuer")

    def test_has_matching_pass_iae(self):
        """
        The search for PE approval screen should redirect to the matching job application details screen if the
        number matches a PASS IAE attached to a job_application
        """
        self.set_up_pe_approval()

        self.client.force_login(self.employer)

        response = self.client.get(self.url, {"number": self.approval.number})
        assert response.status_code == 302

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": self.job_application.id})
        assert response.url == next_url

    def test_has_no_last_accepted_job_application(self):
        """
        In some cases, there is an approval but no matching accepted job application
        """
        self.set_up_pe_approval(with_job_application=True)
        ja = self.job_seeker.job_applications.first()
        ja.state = JobApplicationWorkflow.STATE_CANCELLED
        ja.save()

        self.client.force_login(self.employer)
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
            approval__origin=approvals_enums.Origin.PE_APPROVAL,
            approval__eligibility_diagnosis=None,
            approval__number=pe_approval.number,
            approval__user=job_seeker,
            job_seeker=job_seeker,
        )

        another_company = job_application.to_company
        assert another_company != self.company

        # This is the current user (NOT a member of `another_siae`).
        self.client.force_login(self.employer)

        # The current user should not be able to use the PASS IAE used by another SIAE.
        response = self.client.get(self.url, {"number": job_application.approval.number})
        self.assertNotContains(response, "Continuer")

    def test_unlogged_is_not_authorized(self):
        """
        It is not possible to access the search for PE approval screen unlogged
        """

        response = self.client.get(self.url)
        assert response.status_code == 302
        # TODO: (cms) redirect to prescriber's connection page with a flash message instead.
        # AssertionError: '/login/job_seeker' not found in '/accounts/login/?next=/approvals/pe-approval/search'
        next_url = reverse("account_login")
        assert next_url in response.url

    def test_as_job_seeker_is_not_authorized(self):
        """
        The search for PE approval screen as job seeker is not authorized
        """
        job_application = JobApplicationFactory(with_approval=True)
        self.client.force_login(job_application.job_seeker)

        response = self.client.get(self.url)
        assert response.status_code == 404


class PoleEmploiApprovalSearchUserTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.job_application = JobApplicationFactory(with_approval=True)
        cls.employer = cls.job_application.to_company.members.first()

    def test_nominal(self):
        """
        The search for PE approval screen should redirect to the matching job application details screen if the
        number matches a PASS IAE attached to a job_application
        """
        self.client.force_login(self.employer)
        pe_approval = PoleEmploiApprovalFactory()

        url = reverse("approvals:pe_approval_search_user", kwargs={"pe_approval_id": pe_approval.id})

        response = self.client.get(url)
        self.assertContains(response, pe_approval.last_name.upper())
        self.assertContains(response, pe_approval.first_name.title())

    def test_invalid_pe_approval(self):
        self.client.force_login(self.employer)

        url = reverse("approvals:pe_approval_search_user", kwargs={"pe_approval_id": 123})

        response = self.client.get(url)
        assert response.status_code == 404


class PoleEmploiApprovalCreateTest(TestCase):
    def setUp(self):
        super().setUp()
        self.job_application = JobApplicationFactory(with_approval=True)
        self.company = self.job_application.to_company
        self.employer = self.job_application.to_company.members.first()
        self.approval = self.job_application.approval
        self.job_seeker = self.job_application.job_seeker
        self.pe_approval = PoleEmploiApprovalFactory()

    def test_from_new_user(self):
        """
        When the user does not exist for the suggested email, it is created as well as the approval
        """
        initial_approval_count = Approval.objects.count()
        initial_user_count = User.objects.count()
        self.client.force_login(self.employer)
        email = "some.new@email.com"
        url = reverse("approvals:pe_approval_create", kwargs={"pe_approval_id": self.pe_approval.id})
        params = {"email": email}
        response = self.client.post(url, params)

        new_user = User.objects.get(email=email)

        assert new_user.has_valid_common_approval
        assert new_user.latest_approval.number == self.pe_approval.number
        assert response.status_code == 302
        assert new_user.last_accepted_job_application is not None
        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": new_user.last_accepted_job_application.id}
        )
        assert response.url == next_url
        assert Approval.objects.count() == initial_approval_count + 1
        assert User.objects.count() == initial_user_count + 1

        converted_approval = new_user.approvals.get()
        assert converted_approval.number == self.pe_approval.number
        assert converted_approval.origin == approvals_enums.Origin.PE_APPROVAL
        assert new_user.last_accepted_job_application.origin == job_applications_enums.Origin.PE_APPROVAL

    def test_from_existing_user_without_approval(self):
        """
        When an existing user has no valid approval, it is possible to import a Pôle emploi Approval
        """
        initial_approval_count = Approval.objects.count()
        job_seeker = JobSeekerFactory()
        self.client.force_login(self.employer)

        url = reverse("approvals:pe_approval_create", kwargs={"pe_approval_id": self.pe_approval.id})
        params = {"email": job_seeker.email}
        response = self.client.post(url, params)

        assert response.status_code == 302
        assert Approval.objects.count() == initial_approval_count + 1
        assertMessages(
            response,
            [(messages.SUCCESS, "L'agrément a bien été importé, vous pouvez désormais le prolonger ou le suspendre.")],
        )

        converted_approval = job_seeker.approvals.get()
        assert converted_approval.number == self.pe_approval.number
        assert converted_approval.origin == approvals_enums.Origin.PE_APPROVAL
        assert job_seeker.last_accepted_job_application.origin == job_applications_enums.Origin.PE_APPROVAL

    def test_when_pole_emploi_approval_has_already_been_imported(self):
        """
        When the PoleEmploiApproval has already been imported, we are redirected to its page
        """
        self.job_application = JobApplicationFactory(
            with_approval=True,
            approval=ApprovalFactory(number=self.pe_approval.number[:12], origin_pe_approval=True),
        )

        initial_approval_count = Approval.objects.count()
        job_seeker = JobSeekerFactory()
        self.client.force_login(self.employer)

        url = reverse("approvals:pe_approval_create", kwargs={"pe_approval_id": self.pe_approval.id})
        params = {"email": job_seeker.email}
        response = self.client.post(url, params)

        assert response.status_code == 302
        assert Approval.objects.count() == initial_approval_count
        assertMessages(response, [(messages.INFO, "Cet agrément a déjà été importé.")])

    def test_from_existing_user_with_approval(self):
        """
        When an existing user already has a valid approval, it is not possible to import a Pole Emploi Approval
        """
        assert self.job_seeker.has_valid_common_approval

        initial_approval_count = Approval.objects.count()
        self.client.force_login(self.employer)

        url = reverse("approvals:pe_approval_create", kwargs={"pe_approval_id": self.pe_approval.id})
        params = {"email": self.job_seeker.email}

        response = self.client.post(url, params)

        assert Approval.objects.count() == initial_approval_count
        assert response.status_code == 302
        next_url = reverse("approvals:pe_approval_search_user", kwargs={"pe_approval_id": self.pe_approval.id})
        assert response.url == next_url
        assertMessages(
            response, [(messages.ERROR, "Le candidat associé à cette adresse e-mail a déjà un PASS IAE valide.")]
        )
