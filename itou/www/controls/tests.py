from django.test import TestCase
from django.urls import reverse

from itou.institutions.factories import InstitutionWithMembershipFactory
from itou.institutions.models import Institution
from itou.job_applications.factories import JobApplicationWithApprovalFactory
from itou.siaes.factories import SiaeWithMembershipFactory
from itou.users.factories import DEFAULT_PASSWORD, UserFactory
from itou.www.stats.views import _STATS_HTML_TEMPLATE


class InstitutionNavigationTest(TestCase):
    def test_access_to_stat_page(self):
        institution = InstitutionWithMembershipFactory(kind=Institution.Kind.DDETS, department="14")
        user = institution.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("stats:stats_ddets_diagnosis_control")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, _STATS_HTML_TEMPLATE)
        self.assertContains(response, "Adapter le ratio de mon département")
        self.assertContains(response, "Valider le paramètre de contrôle national")

    def test_cannot_access_to_stat_page_for_other_users(self):
        user = UserFactory()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("stats:stats_ddets_diagnosis_control")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_access_to_review_page(self):
        institution = InstitutionWithMembershipFactory(kind=Institution.Kind.DDETS, department="14")
        user = institution.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("controls:review_self_approvals")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "controls/review_self_approvals.html")
        self.assertEqual(response.context["institution"], institution)

    def test_cannot_access_to_review_page_for_other_users(self):
        user = UserFactory()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("controls:review_self_approvals")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_backlink_on_self_approval_list(self):
        self.assertTrue(False)

    def test_backlink_on_self_approval_detail(self):
        self.assertTrue(False)


class SiaeNavigationTest(TestCase):
    def test_access_to_self_approval_list(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.last()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("controls:self_approvals_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "controls/self_approvals_list.html")
        self.assertEqual(response.context["siae"], siae)
        # backlink
        self.assertContains(response, reverse("dashboard:index"))

    def test_cannot_access_to_self_approval_list_for_not_siae_members(self):
        user = UserFactory()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("controls:self_approvals_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_access_self_approval_detail_for_siae_members(self):
        siae = SiaeWithMembershipFactory()
        job_application = JobApplicationWithApprovalFactory(to_siae=siae)
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("controls:self_approvals", args=(job_application.approval_id,))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "controls/self_approvals.html")
        self.assertEqual(response.context["siae"], siae)
        self.assertEqual(response.context["job_application"], job_application)
        # backlink
        self.assertContains(response, reverse("controls:self_approvals_list"))

    def test_cannot_access_self_approval_detail_for_members_of_an_other_siae(self):
        siae1 = SiaeWithMembershipFactory()
        user = siae1.members.first()

        siae2 = SiaeWithMembershipFactory()
        job_application2 = JobApplicationWithApprovalFactory(to_siae=siae2)

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("controls:self_approvals", args=(job_application2.approval_id,))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_cannot_access_self_approval_detail_for_not_siae_members(self):
        user = UserFactory()

        siae2 = SiaeWithMembershipFactory()
        job_application2 = JobApplicationWithApprovalFactory(to_siae=siae2)

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("controls:self_approvals", args=(job_application2.approval_id,))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
