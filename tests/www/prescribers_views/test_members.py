import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from tests.invitations.factories import PrescriberWithOrgInvitationFactory
from tests.prescribers.factories import (
    PrescriberFactory,
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWith2MembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)


class TestMembers:
    MORE_ADMIN_MSG = "Nous vous recommandons de nommer plusieurs administrateurs"

    def test_members(self, client):
        organization = PrescriberOrganizationWithMembershipFactory()
        user = organization.members.first()
        client.force_login(user)
        url = reverse("prescribers_views:members")
        response = client.get(url)
        assert response.status_code == 200

    def test_active_members(self, client):
        organization = PrescriberOrganizationFactory()
        active_member_active_user = PrescriberMembershipFactory(organization=organization)
        active_member_inactive_user = PrescriberMembershipFactory(organization=organization, user__is_active=False)
        inactive_member_active_user = PrescriberMembershipFactory(organization=organization, is_active=False)
        inactive_member_inactive_user = PrescriberMembershipFactory(
            organization=organization, is_active=False, user__is_active=False
        )

        client.force_login(active_member_active_user.user)
        url = reverse("prescribers_views:members")
        response = client.get(url)
        assert response.status_code == 200
        assert len(response.context["members"]) == 1
        assert active_member_active_user in response.context["members"]
        assert active_member_inactive_user not in response.context["members"]
        assert inactive_member_active_user not in response.context["members"]
        assert inactive_member_inactive_user not in response.context["members"]

    def test_members_admin_warning_one_user(self, client):
        organization = PrescriberOrganizationWithMembershipFactory()
        user = organization.members.first()
        client.force_login(user)
        url = reverse("prescribers_views:members")
        response = client.get(url)
        assertNotContains(response, self.MORE_ADMIN_MSG)

    def test_members_admin_warning_two_users(self, client):
        organization = PrescriberOrganizationWith2MembershipFactory()
        user = organization.members.first()
        client.force_login(user)
        url = reverse("prescribers_views:members")
        response = client.get(url)
        assertContains(response, self.MORE_ADMIN_MSG)

        # Set all users admins
        organization.memberships.update(is_admin=True)
        response = client.get(url)
        assertNotContains(response, self.MORE_ADMIN_MSG)

    def test_members_admin_warning_many_users(self, client):
        organization = PrescriberOrganizationWith2MembershipFactory()
        PrescriberMembershipFactory(organization=organization, user__is_active=False)
        PrescriberMembershipFactory(organization=organization, is_admin=False, user__is_active=False)
        user = organization.members.first()
        client.force_login(user)
        url = reverse("prescribers_views:members")
        response = client.get(url)
        assertContains(response, self.MORE_ADMIN_MSG)


class TestUserMembershipDeactivation:
    def test_self_deactivation(self, client):
        """
        A user, even if admin, can't self-deactivate
        (must be done by another admin)
        """
        organization = PrescriberOrganizationWithMembershipFactory()
        admin = organization.members.filter(prescribermembership__is_admin=True).first()
        memberships = admin.prescribermembership_set.all()
        membership = memberships.first()

        client.force_login(admin)
        url = reverse("prescribers_views:deactivate_member", kwargs={"public_id": admin.public_id})
        response = client.post(url)
        assert response.status_code == 403

        # Trying to change self membership is not allowed
        # but does not raise an error (does nothing)
        membership.refresh_from_db()
        assert membership.is_active

    def test_deactivate_user(self, caplog, client, mailoutbox, snapshot):
        """
        Standard use case of user deactivation.
        Everything should be fine ...
        """
        organization = PrescriberOrganizationWith2MembershipFactory(name="Mission locale", email="ml@mailinator.com")
        admin = organization.members.filter(prescribermembership__is_admin=True).first()
        guest = organization.members.filter(prescribermembership__is_admin=False).first()

        memberships = guest.prescribermembership_set.all()
        membership = memberships.first()

        received_invitation = PrescriberWithOrgInvitationFactory(email=guest.email, organization=organization)
        sent_invitation = PrescriberWithOrgInvitationFactory(sender=guest, organization=organization)
        sent_invitation_to_other = PrescriberWithOrgInvitationFactory(sender=guest)

        client.force_login(admin)
        url = reverse("prescribers_views:deactivate_member", kwargs={"public_id": guest.public_id})
        response = client.post(url)
        assert response.status_code == 302

        # User should be deactivated now
        membership.refresh_from_db()
        assert not membership.is_active
        assert admin == membership.updated_by
        assert membership.updated_at is not None
        assert (
            f"Expired 1 invitations to prescribers.PrescriberOrganization {organization.pk} for user_id={guest.pk}."
            in caplog.messages
        )
        assert (
            f"Expired 1 invitations to prescribers.PrescriberOrganization {organization.pk} from user_id={guest.pk}."
            in caplog.messages
        )
        assert (
            f"User {admin.pk} deactivated prescribers.PrescriberMembership of organization_id={organization.pk} "
            f"for user_id={guest.pk} is_admin=False."
        ) in caplog.messages

        # Check mailbox
        # User must have been notified of deactivation (we're human after all)
        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert f"[DEV] [Désactivation] Vous n'êtes plus membre de {organization.display_name}" == email.subject
        assert "Un administrateur vous a retiré d'une structure sur les emplois de l'inclusion" in email.body
        assert email.to[0] == guest.email
        assert email.body == snapshot
        received_invitation.refresh_from_db()
        assert received_invitation.has_expired is True
        sent_invitation.refresh_from_db()
        assert sent_invitation.has_expired is True
        sent_invitation_to_other.refresh_from_db()
        assert sent_invitation_to_other.has_expired is False

    def test_deactivate_user_from_another_organisation(self, client, mailoutbox):
        my_organization = PrescriberOrganizationFactory()
        other_organization = PrescriberOrganizationFactory()
        my_membership = PrescriberMembershipFactory(organization=my_organization, is_admin=True)
        other_membership = PrescriberMembershipFactory(organization=other_organization)

        client.force_login(my_membership.user)
        response = client.post(
            reverse(
                "prescribers_views:deactivate_member",
                kwargs={"public_id": other_membership.user.public_id},
            ),
        )

        assert response.status_code == 404
        other_membership.refresh_from_db()
        assert other_membership.is_active is True
        assert mailoutbox == []

    def test_deactivate_with_no_perms(self, client):
        """
        Non-admin user can't change memberships
        """
        organization = PrescriberOrganizationWithMembershipFactory()
        guest = PrescriberFactory()
        organization.members.add(guest)

        client.force_login(guest)
        url = reverse("prescribers_views:deactivate_member", kwargs={"public_id": guest.public_id})
        response = client.post(url)
        assert response.status_code == 403

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_deactivate_inactive_member(self, client, method, mailoutbox):
        organization = PrescriberOrganizationFactory()
        admin_membership = PrescriberMembershipFactory(organization=organization, is_admin=True)
        guest_membership = PrescriberMembershipFactory(organization=organization, is_active=False)

        client.force_login(admin_membership.user)
        request = getattr(client, method)
        response = request(
            reverse("prescribers_views:deactivate_member", kwargs={"public_id": guest_membership.user.public_id})
        )
        assert response.status_code == 404
        guest_membership.refresh_from_db()
        assert guest_membership.is_active is False
        assert mailoutbox == []

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_deactivate_non_member(self, client, method, mailoutbox):
        organization = PrescriberOrganizationFactory()
        admin_membership = PrescriberMembershipFactory(organization=organization, is_admin=True)
        other_user = PrescriberFactory()
        client.force_login(admin_membership.user)
        request = getattr(client, method)
        response = request(reverse("prescribers_views:deactivate_member", kwargs={"public_id": other_user.public_id}))
        assert response.status_code == 404
        assert mailoutbox == []

    def test_deactivated_prescriber_is_orienter(self, client):
        """
        A prescriber deactivated from a prescriber organization
        and without any membership becomes an "orienteur".
        As such he must be able to login.
        """
        organization = PrescriberOrganizationWith2MembershipFactory()
        admin = organization.members.filter(prescribermembership__is_admin=True).first()
        guest = organization.members.filter(prescribermembership__is_admin=False).first()

        client.force_login(admin)
        url = reverse("prescribers_views:deactivate_member", kwargs={"public_id": guest.public_id})
        response = client.post(url)
        assert response.status_code == 302

        # guest is now an orienter
        client.force_login(guest)
        url = reverse("dashboard:index")
        response = client.post(url)
        assert response.status_code == 200

    def test_deactivate_admin(self, caplog, client, mailoutbox):
        organization = PrescriberOrganizationFactory()
        admin_membership = PrescriberMembershipFactory(organization=organization, is_admin=True)
        other_admin_membership = PrescriberMembershipFactory(organization=organization, is_admin=True)
        other_admin = other_admin_membership.user
        invitation = PrescriberWithOrgInvitationFactory(email=other_admin.email, organization=organization)

        client.force_login(admin_membership.user)
        response = client.post(
            reverse("prescribers_views:deactivate_member", kwargs={"public_id": other_admin.public_id})
        )

        assertRedirects(response, reverse("prescribers_views:members"))
        other_admin_membership.refresh_from_db()
        assert other_admin_membership.is_active is False
        assert other_admin_membership.updated_by_id == admin_membership.user_id
        assert other_admin_membership.updated_at is not None
        assert (
            f"Expired 1 invitations to prescribers.PrescriberOrganization {organization.pk} "
            f"for user_id={other_admin.pk}."
        ) in caplog.messages
        assert (
            f"Expired 0 invitations to prescribers.PrescriberOrganization {organization.pk} "
            f"from user_id={other_admin.pk}."
        ) in caplog.messages
        assert (
            f"User {admin_membership.user_id} deactivated prescribers.PrescriberMembership "
            f"of organization_id={organization.pk} for user_id={other_admin.pk} is_admin=True."
        ) in caplog.messages
        [email] = mailoutbox
        assert f"[DEV] [Désactivation] Vous n'êtes plus membre de {organization.display_name}" == email.subject
        assert "Un administrateur vous a retiré d'une structure sur les emplois de l'inclusion" in email.body
        assert email.to == [other_admin_membership.user.email]
        invitation.refresh_from_db()
        assert invitation.has_expired is True

    def test_structure_selector(self, client):
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
        client.force_login(admin)
        url = reverse("prescribers_views:deactivate_member", kwargs={"public_id": guest.public_id})
        response = client.post(url)
        assert response.status_code == 302
        client.logout()

        # guest must be able to login
        client.force_login(guest)
        url = reverse("dashboard:index")
        response = client.get(url)

        # Wherever guest lands should give a 200 OK
        assert response.status_code == 200

        # Check response context, only one prescriber organization should remain
        assert len(response.context["request"].organizations) == 1
