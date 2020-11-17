from unittest import mock

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch

from itou.prescribers.factories import (
    PrescriberFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWith2MembershipFactory,
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

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_edit_with_multiple_memberships_and_same_siret(self, mock_call_ban_geocoding_api):
        """
        Updating information of the prescriber organization must be possible
        when user is member of multiple orgs with the same SIRET (and different types)
        (was a regression)
        """
        organization = PrescriberOrganizationWithMembershipFactory(kind="ML")
        siret = organization.siret
        user = organization.members.first()

        org2 = PrescriberOrganizationWithMembershipFactory(kind="PLIE", siret=siret)
        org2.members.add(user)
        org2.save()

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("prescribers_views:edit_organization")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "siret": siret,
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

        url = reverse("dashboard:index")
        self.assertEqual(url, response.url)


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
        url = reverse("prescribers_views:deactivate_member", kwargs={"user_id": admin.id})
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
        organization = PrescriberOrganizationWith2MembershipFactory()
        admin, guest = organization.members.all()

        memberships = guest.prescribermembership_set.all()
        membership = memberships.first()

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:deactivate_member", kwargs={"user_id": guest.id})
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
        self.assertIn("[Désactivation] Vous n'êtes plus membre de", email.subject)
        self.assertIn("Un administrateur vous a retiré d'une structure sur la Plateforme de l'inclusion", email.body)
        self.assertEqual(email.to[0], guest.email)

    def test_deactivate_with_no_perms(self):
        """
        Non-admin user can't change memberships
        """
        organization = PrescriberOrganizationWithMembershipFactory()
        guest = PrescriberFactory()
        organization.members.add(guest)

        self.client.login(username=guest.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

    def test_deactivated_prescriber_is_orienter(self):
        """
        A prescriber deactivated from a prescriber organization
        and without any membership becomes an "orienteur".
        As such he must be able to login.
        """
        organization = PrescriberOrganizationWith2MembershipFactory()
        admin, guest = organization.members.all()

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        # guest is now an orienter
        self.client.login(username=guest.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:index")
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)

    def test_structure_selector(self):
        """
        Check that a deactivated member can't access the structure
        from dashboard selector
        """
        organization2 = PrescriberOrganizationWithMembershipFactory()
        guest = organization2.members.first()

        organization1 = PrescriberOrganizationWithMembershipFactory()
        admin = organization1.members.first()
        organization1.members.add(guest)

        memberships = guest.prescribermembership_set.all()
        self.assertEqual(len(memberships), 2)

        # Admin remove guest from structure
        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.client.logout()

        # guest must be able to login
        self.client.login(username=guest.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:index")
        response = self.client.get(url)

        # Wherever guest lands should give a 200 OK
        self.assertEqual(response.status_code, 200)

        # Check response context, only one prescriber organization should remain
        self.assertEqual(len(response.context["user_prescriberorganizations"]), 1)


class PrescribersOrganizationAdminMembersManagementTest(TestCase):
    def test_add_admin(self):
        """
        Check the ability for an admin to add another admin to the organization
        """
        organization = PrescriberOrganizationWith2MembershipFactory()
        admin, guest = organization.members.all()

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        # Redirection to confirm page
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Confirm action
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        organization.refresh_from_db()
        self.assertTrue(guest in organization.active_admin_members)

    def test_remove_admin(self):
        """
        Check the ability for an admin to remove another admin
        """
        organization = PrescriberOrganizationWith2MembershipFactory()
        admin, guest = organization.members.all()

        membership = guest.prescribermembership_set.first()
        membership.is_admin = True
        membership.save()
        self.assertTrue(guest in organization.active_admin_members)

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:update_admin_role", kwargs={"action": "remove", "user_id": guest.id})

        # Redirection to confirm page
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Confirm action
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        organization.refresh_from_db()
        self.assertFalse(guest in organization.active_admin_members)

    def test_admin_management_permissions(self):
        """
        Non-admin users can't update admin members
        """
        organization = PrescriberOrganizationWith2MembershipFactory()
        admin, guest = organization.members.all()

        self.client.login(username=guest.email, password=DEFAULT_PASSWORD)
        url = reverse("prescribers_views:update_admin_role", kwargs={"action": "remove", "user_id": admin.id})

        # Redirection to confirm page
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Confirm action
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

        # Add self as admin with no privilege
        url = reverse("prescribers_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

    def test_suspicious_action(self):
        """
        Test "suspicious" actions: action code not registered for use (even if admin)
        """
        suspicious_action = "h4ckm3"
        organization = PrescriberOrganizationWith2MembershipFactory()
        admin, guest = organization.members.all()

        self.client.login(username=guest.email, password=DEFAULT_PASSWORD)

        # update: possible actions are now filtered via RE_PATH in urls.py
        with self.assertRaises(NoReverseMatch):
            reverse("prescribers_views:update_admin_role", kwargs={"action": suspicious_action, "user_id": admin.id})
