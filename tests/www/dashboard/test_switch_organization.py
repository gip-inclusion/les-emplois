from django.urls import reverse

from tests.companies.factories import (
    CompanyAfterGracePeriodFactory,
    CompanyFactory,
    CompanyPendingGracePeriodFactory,
)
from tests.institutions.factories import InstitutionFactory, InstitutionMembershipFactory, LaborInspectorFactory
from tests.prescribers import factories as prescribers_factories
from tests.users.factories import (
    JobSeekerFactory,
    PrescriberFactory,
)
from tests.utils.test import TestCase


class SwitchCompanyTest(TestCase):
    def test_switch_company(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        self.client.force_login(user)

        related_company = CompanyFactory(with_membership=True)
        related_company.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == company

        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == company
        assert response.context["siae"] == company

        url = reverse("dashboard:switch_organization")
        response = self.client.post(url, data={"organization_id": related_company.pk})
        assert response.status_code == 302

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_company

        url = reverse("companies_views:card", kwargs={"siae_id": related_company.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_company
        assert response.context["siae"] == related_company

        url = reverse("companies_views:job_description_list")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_company

        url = reverse("apply:list_for_siae")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_company

    def test_can_still_switch_to_inactive_company_during_grace_period(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        self.client.force_login(user)

        related_company = CompanyPendingGracePeriodFactory(with_membership=True)
        related_company.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == company

        url = reverse("dashboard:switch_organization")
        response = self.client.post(url, data={"organization_id": related_company.pk})
        assert response.status_code == 302

        # User has indeed switched.
        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_company

    def test_cannot_switch_to_inactive_company_after_grace_period(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        self.client.force_login(user)

        related_company = CompanyAfterGracePeriodFactory()
        related_company.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == company

        # Switching to that company is not even possible in practice because
        # it does not even show up in the menu.
        url = reverse("dashboard:switch_organization")
        response = self.client.post(url, data={"organization_id": related_company.pk})
        assert response.status_code == 404

        # User is still working on the main active company.
        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == company


class SwitchOrganizationTest(TestCase):
    def test_not_allowed_user(self):
        organization = prescribers_factories.PrescriberOrganizationFactory()

        for user in (
            JobSeekerFactory(),
            PrescriberFactory(),
        ):
            self.client.force_login(user)
            url = reverse("dashboard:switch_organization")
            response = self.client.post(url, data={"organization_id": organization.pk})
            assert response.status_code == 404

    def test_usual_case(self):
        url = reverse("dashboard:switch_organization")

        user = PrescriberFactory()
        orga1 = prescribers_factories.PrescriberMembershipFactory(user=user).organization
        orga2 = prescribers_factories.PrescriberMembershipFactory(user=user).organization
        self.client.force_login(user)

        response = self.client.post(url, data={"organization_id": orga1.pk})
        assert response.status_code == 302

        response = self.client.get(reverse("dashboard:index"))
        assert response.status_code == 200
        assert response.context["request"].current_organization == orga1

        response = self.client.post(url, data={"organization_id": orga2.pk})
        assert response.status_code == 302

        response = self.client.get(reverse("dashboard:index"))
        assert response.status_code == 200
        assert response.context["request"].current_organization == orga2


class SwitchInstitutionTest(TestCase):
    def test_not_allowed_user(self):
        institution = InstitutionFactory()

        for user in (
            JobSeekerFactory(),
            # Create a user with other membership
            # (otherwise the middleware intercepts labor inspector without any membership)
            InstitutionMembershipFactory().user,
        ):
            self.client.force_login(user)
            url = reverse("dashboard:switch_organization")
            response = self.client.post(url, data={"organization_id": institution.pk})
            assert response.status_code == 404

    def test_usual_case(self):
        url = reverse("dashboard:switch_organization")

        user = LaborInspectorFactory()
        institution1 = InstitutionMembershipFactory(user=user).institution
        institution2 = InstitutionMembershipFactory(user=user).institution
        self.client.force_login(user)

        response = self.client.post(url, data={"organization_id": institution1.pk})
        assert response.status_code == 302

        response = self.client.get(reverse("dashboard:index"))
        assert response.status_code == 200
        assert response.context["request"].current_organization == institution1

        response = self.client.post(url, data={"organization_id": institution2.pk})
        assert response.status_code == 302

        response = self.client.get(reverse("dashboard:index"))
        assert response.status_code == 200
        assert response.context["request"].current_organization == institution2
