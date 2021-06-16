from django.core import mail
from django.test import TestCase
from django.urls import reverse

from itou.prescribers.factories import (
    PrescriberFactory,
    PrescriberOrganizationWith2MembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from itou.users.factories import DEFAULT_PASSWORD


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
        admin = organization.members.filter(prescribermembership__is_admin=True).first()
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
        admin = organization.members.filter(prescribermembership__is_admin=True).first()
        guest = organization.members.filter(prescribermembership__is_admin=False).first()

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
        self.assertEqual(f"[Désactivation] Vous n'êtes plus membre de {organization.display_name}", email.subject)
        self.assertIn("Un administrateur vous a retiré d'une structure sur les emplois de l'inclusion", email.body)
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
        admin = organization.members.filter(prescribermembership__is_admin=True).first()
        guest = organization.members.filter(prescribermembership__is_admin=False).first()

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
