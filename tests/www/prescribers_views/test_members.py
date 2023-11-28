from django.core import mail
from django.urls import reverse

from tests.prescribers.factories import (
    PrescriberFactory,
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWith2MembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from tests.utils.test import TestCase


class MembersTest(TestCase):
    def test_members(self):
        organization = PrescriberOrganizationWithMembershipFactory()
        user = organization.members.first()
        self.client.force_login(user)
        url = reverse("prescribers_views:members")
        response = self.client.get(url)
        assert response.status_code == 200

    def test_active_members(self):
        organization = PrescriberOrganizationFactory()
        active_member_active_user = PrescriberMembershipFactory(organization=organization)
        active_member_inactive_user = PrescriberMembershipFactory(organization=organization, user__is_active=False)
        inactive_member_active_user = PrescriberMembershipFactory(organization=organization, is_active=False)
        inactive_member_inactive_user = PrescriberMembershipFactory(
            organization=organization, is_active=False, user__is_active=False
        )

        self.client.force_login(active_member_active_user.user)
        url = reverse("prescribers_views:members")
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.context["members"]) == 1
        assert active_member_active_user in response.context["members"]
        assert active_member_inactive_user not in response.context["members"]
        assert inactive_member_active_user not in response.context["members"]
        assert inactive_member_inactive_user not in response.context["members"]


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

        self.client.force_login(admin)
        url = reverse("prescribers_views:deactivate_member", kwargs={"user_id": admin.id})
        response = self.client.post(url)
        assert response.status_code == 403

        # Trying to change self membership is not allowed
        # but does not raise an error (does nothing)
        membership.refresh_from_db()
        assert membership.is_active

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

        self.client.force_login(admin)
        url = reverse("prescribers_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        assert response.status_code == 302

        # User should be deactivated now
        membership.refresh_from_db()
        assert not membership.is_active
        assert admin == membership.updated_by
        assert membership.updated_at is not None

        # Check mailbox
        # User must have been notified of deactivation (we're human after all)
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert f"[Désactivation] Vous n'êtes plus membre de {organization.display_name}" == email.subject
        assert "Un administrateur vous a retiré d'une structure sur les emplois de l'inclusion" in email.body
        assert email.to[0] == guest.email

    def test_deactivate_with_no_perms(self):
        """
        Non-admin user can't change memberships
        """
        organization = PrescriberOrganizationWithMembershipFactory()
        guest = PrescriberFactory()
        organization.members.add(guest)

        self.client.force_login(guest)
        url = reverse("prescribers_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        assert response.status_code == 403

    def test_deactivated_prescriber_is_orienter(self):
        """
        A prescriber deactivated from a prescriber organization
        and without any membership becomes an "orienteur".
        As such he must be able to login.
        """
        organization = PrescriberOrganizationWith2MembershipFactory()
        admin = organization.members.filter(prescribermembership__is_admin=True).first()
        guest = organization.members.filter(prescribermembership__is_admin=False).first()

        self.client.force_login(admin)
        url = reverse("prescribers_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        assert response.status_code == 302

        # guest is now an orienter
        self.client.force_login(guest)
        url = reverse("dashboard:index")
        response = self.client.post(url)
        assert response.status_code == 200

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
        assert len(memberships) == 2

        # Admin remove guest from structure
        self.client.force_login(admin)
        url = reverse("prescribers_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        assert response.status_code == 302
        self.client.logout()

        # guest must be able to login
        self.client.force_login(guest)
        url = reverse("dashboard:index")
        response = self.client.get(url)

        # Wherever guest lands should give a 200 OK
        assert response.status_code == 200

        # Check response context, only one prescriber organization should remain
        assert len(response.context["request"].organizations) == 1
