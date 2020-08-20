from django.test import TestCase
from django.urls import reverse

from itou.prescribers.factories import PrescriberOrganizationFactory, PrescriberOrganizationWithMembershipFactory
from itou.prescribers.models import PrescriberOrganization
from itou.users.factories import DEFAULT_PASSWORD


class CardViewTest(TestCase):
    def test_card(self):
        prescriber_org = PrescriberOrganizationFactory(is_authorized=True)
        url = reverse("prescribers_views:card", kwargs={"org_id": prescriber_org.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["prescriber_org"], prescriber_org)


class EditOrganizationTest(TestCase):
    def test_edit(self):
        """Edit a prescriber organization."""

        organization = PrescriberOrganizationWithMembershipFactory()
        user = organization.members.first()

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("prescribers_views:edit_organization")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "name": "foo",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-siae.com",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        organization = PrescriberOrganization.objects.get(siret=organization.siret)

        self.assertEqual(organization.description, post_data["description"])
        self.assertEqual(organization.email, post_data["email"])
        self.assertEqual(organization.phone, post_data["phone"])
        self.assertEqual(organization.website, post_data["website"])


class MembersTest(TestCase):
    def test_members(self):
        organization = PrescriberOrganizationWithMembershipFactory()
        user = organization.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:members")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
