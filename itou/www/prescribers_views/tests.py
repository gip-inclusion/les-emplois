from unittest import mock

from django.test import TestCase
from django.urls import reverse

from itou.prescribers.models import PrescriberOrganization
from itou.users.factories import DEFAULT_PASSWORD
from itou.users.factories import PrescriberFactory
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.mocks.siret import API_INSEE_SIRET_RESULT_MOCK


class ViewsTest(TestCase):
    @mock.patch(
        "itou.utils.apis.siret.call_insee_api", return_value=API_INSEE_SIRET_RESULT_MOCK
    )
    @mock.patch(
        "itou.utils.apis.geocoding.call_ban_geocoding_api",
        return_value=BAN_GEOCODING_API_RESULT_MOCK,
    )
    def test_create_prescriber_organization(
        self, mock_call_ban_geocoding_api, mock_call_insee_api
    ):
        """Create prescriber organization."""

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
