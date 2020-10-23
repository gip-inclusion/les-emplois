from unittest import mock

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from itou.prescribers.factories import (
    PrescriberFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from itou.prescribers.models import PrescriberOrganization
from itou.users.factories import DEFAULT_PASSWORD
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK


class CardViewTest(TestCase):
    def test_card(self):
        prescriber_org = PrescriberOrganizationFactory(is_authorized=True)
        url = reverse("prescribers_views:card", kwargs={"org_id": prescriber_org.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["prescriber_org"], prescriber_org)


class EditOrganizationTest(TestCase):
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_edit(self, mock_call_ban_geocoding_api):
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
            "address_line_1": "2 Rue de Soufflenheim",
            "address_line_2": "",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-siae.com",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        mock_call_ban_geocoding_api.assert_called_once()

        organization = PrescriberOrganization.objects.get(siret=organization.siret)

        self.assertEqual(organization.description, post_data["description"])
        self.assertEqual(organization.address_line_1, post_data["address_line_1"])
        self.assertEqual(organization.address_line_2, post_data["address_line_2"])
        self.assertEqual(organization.city, post_data["city"])
        self.assertEqual(organization.post_code, post_data["post_code"])
        self.assertEqual(organization.department, post_data["department"])
        self.assertEqual(organization.email, post_data["email"])
        self.assertEqual(organization.phone, post_data["phone"])
        self.assertEqual(organization.website, post_data["website"])

        # This data comes from BAN_GEOCODING_API_RESULT_MOCK.
        self.assertEqual(organization.coords, "SRID=4326;POINT (2.316754 48.838411)")
        self.assertEqual(organization.latitude, 48.838411)
        self.assertEqual(organization.longitude, 2.316754)
        self.assertEqual(organization.geocoding_score, 0.587663373207207)


class MembersTest(TestCase):
    def test_members(self):
        organization = PrescriberOrganizationWithMembershipFactory()
        user = organization.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:members")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class UserMembershipDeactivationTest(TestCase):
    def test_self_deactivation(self):
        """
        A user, even if admin, can't self-deactivate
        (must be done by another admin)
        """
        organization = PrescriberOrganizationWithMembershipFactory()
        admin = organization.members.first()
        memberships = admin.prescribermembership_set.all()
        membership = memberships.first()

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:toggle_membership", kwargs={"membership_id": membership.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

        # Trying to change self membership is not allowed
        # but does not raise an error (does nothing)
        membership.refresh_from_db()
        self.assertTrue(membership.is_active)

    def test_deactivate_user(self):
        """
        Standard use case of user deactivation.
        Everything should be fine ...
        """
        organization = PrescriberOrganizationWithMembershipFactory()
        admin = organization.members.first()
        guest = PrescriberFactory()
        organization.members.add(guest)

        memberships = guest.prescribermembership_set.all()
        membership = memberships.first()

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:toggle_membership", kwargs={"membership_id": membership.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        # User should be deactivated now
        membership.refresh_from_db()
        self.assertFalse(membership.is_active)
        self.assertEqual(admin, membership.updated_by)
        self.assertIsNotNone(membership.updated_at)

        # Check mailbox
        # User must have been notified of deactivation (we're human after all)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("[Désactivation] Vous n'étes plus membre d'une organisation", email.subject)
        self.assertIn("Un administrateur vous a retiré d'une structure sur la Plateforme de l'inclusion", email.body)
        self.assertEqual(email.to[0], guest.email)

    def test_deactivate_with_no_perms(self):
        """
        Non-admin user can't change memberships
        """
        organization = PrescriberOrganizationWithMembershipFactory()
        guest = PrescriberFactory()
        organization.members.add(guest)
        memberships = guest.prescribermembership_set.all()
        membership = memberships.first()

        self.client.login(username=guest.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:toggle_membership", kwargs={"membership_id": membership.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

    def test_reactivate_user(self):
        """
        Reactivate a previously deactivated user
        Not yet in scope: but should work
        """
        organization = PrescriberOrganizationWithMembershipFactory()
        admin = organization.members.first()
        guest = PrescriberFactory()
        organization.members.add(guest)

        memberships = guest.prescribermembership_set.all()
        membership = memberships.first()

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:toggle_membership", kwargs={"membership_id": membership.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        # Call a second time to reactivate
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        membership.refresh_from_db()
        self.assertTrue(membership.is_active)

        # No email sent at the moment (reactivation is not enabled)

    def test_deactivated_prescriber_is_orienter(self):
        """
        A prescriber deactivated from a prescriber organization
        and without any membership becomes an "orienteur".
        As such he must be able to login.
        """
        organization = PrescriberOrganizationWithMembershipFactory()
        admin = organization.members.first()
        guest = PrescriberFactory()
        organization.members.add(guest)

        memberships = guest.prescribermembership_set.all()
        membership = memberships.first()

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:toggle_membership", kwargs={"membership_id": membership.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        # guest is now an orienter
        self.client.login(username=guest.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:index")
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
