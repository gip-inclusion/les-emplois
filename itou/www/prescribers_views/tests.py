from unittest import mock

from django.test import TestCase
from django.urls import reverse

from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.prescribers.models import PrescriberOrganization
from itou.users.factories import DEFAULT_PASSWORD, PrescriberFactory
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.mocks.siret import API_INSEE_SIRET_RESULT_MOCK


class CreateOrganizationTest(TestCase):
    @mock.patch(
        "itou.utils.apis.siret.call_insee_api", return_value=API_INSEE_SIRET_RESULT_MOCK
    )
    @mock.patch(
        "itou.utils.apis.geocoding.call_ban_geocoding_api",
        return_value=BAN_GEOCODING_API_RESULT_MOCK,
    )
    def test_create(self, mock_call_ban_geocoding_api, mock_call_insee_api):
        """Create a prescriber organization."""

        user = PrescriberFactory()
        self.assertTrue(
            self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        )

        url = reverse("prescribers_views:create_organization")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "siret": "12000015300011",
            "phone": "",
            "email": "",
            "website": "",
            "description": "",
        }
        response = self.client.post(url, data=post_data)
        mock_call_insee_api.assert_called_once_with(post_data["siret"])
        mock_call_ban_geocoding_api.assert_called_once()
        self.assertEqual(response.status_code, 302)

        organization = PrescriberOrganization.objects.get(siret=post_data["siret"])
        self.assertIn(user, organization.members.all())
        self.assertEqual(1, organization.members.count())

        self.assertIn(organization, user.prescriberorganization_set.all())
        self.assertEqual(1, user.prescriberorganization_set.count())

        membership = user.prescribermembership_set.get(organization=organization)
        self.assertTrue(membership.is_admin)


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
