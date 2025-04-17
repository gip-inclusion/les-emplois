import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from tests.common_apps.organizations.tests import assert_set_admin_role_creation, assert_set_admin_role_removal
from tests.institutions.factories import (
    InstitutionFactory,
    InstitutionMembershipFactory,
    InstitutionWith2MembershipFactory,
    InstitutionWithMembershipFactory,
    LaborInspectorFactory,
)
from tests.invitations.factories import LaborInspectorInvitationFactory


class TestMembers:
    MORE_ADMIN_MSG = "Nous vous recommandons de nommer plusieurs administrateurs"

    def test_members(self, client):
        institution = InstitutionWithMembershipFactory()
        user = institution.members.first()
        client.force_login(user)
        url = reverse("institutions_views:members")
        response = client.get(url)
        assert response.status_code == 200

    def test_active_members(self, client):
        institution = InstitutionFactory()
        active_member_active_user = InstitutionMembershipFactory(institution=institution)
        active_member_inactive_user = InstitutionMembershipFactory(institution=institution, user__is_active=False)
        inactive_member_active_user = InstitutionMembershipFactory(institution=institution, is_active=False)
        inactive_member_inactive_user = InstitutionMembershipFactory(
            institution=institution, is_active=False, user__is_active=False
        )

        client.force_login(active_member_active_user.user)
        url = reverse("institutions_views:members")
        response = client.get(url)
        assert response.status_code == 200
        assert len(response.context["members"]) == 1
        assert active_member_active_user in response.context["members"]
        assert active_member_inactive_user not in response.context["members"]
        assert inactive_member_active_user not in response.context["members"]
        assert inactive_member_inactive_user not in response.context["members"]

    def test_members_admin_warning_one_user(self, client):
        institution = InstitutionWithMembershipFactory()
        user = institution.members.first()
        client.force_login(user)
        url = reverse("institutions_views:members")
        response = client.get(url)
        assertNotContains(response, self.MORE_ADMIN_MSG)

    def test_members_admin_warning_two_users(self, client):
        institution = InstitutionWith2MembershipFactory()
        user = institution.members.first()
        client.force_login(user)
        url = reverse("institutions_views:members")
        response = client.get(url)
        assertContains(response, self.MORE_ADMIN_MSG)

        # Set all users admins
        institution.memberships.update(is_admin=True)
        response = client.get(url)
        assertNotContains(response, self.MORE_ADMIN_MSG)

    def test_members_admin_warning_many_users(self, client):
        institution = InstitutionWith2MembershipFactory()
        InstitutionMembershipFactory(institution=institution, user__is_active=False)
        InstitutionMembershipFactory(institution=institution, is_admin=False, user__is_active=False)
        user = institution.members.first()
        client.force_login(user)
        url = reverse("institutions_views:members")
        response = client.get(url)
        assertContains(response, self.MORE_ADMIN_MSG)

    def test_add_admin(self, client, mailoutbox):
        """
        Check the ability for an admin to add another admin to the company
        """
        institution = InstitutionWith2MembershipFactory()
        admin = institution.members.filter(institutionmembership__is_admin=True).first()
        guest = institution.members.filter(institutionmembership__is_admin=False).first()

        client.force_login(admin)
        url = reverse("institutions_views:update_admin_role", kwargs={"action": "add", "public_id": guest.public_id})

        # Redirection to confirm page
        response = client.get(url)
        assert response.status_code == 200

        # Confirm action
        response = client.post(url)
        assert response.status_code == 302

        institution.refresh_from_db()
        assert_set_admin_role_creation(guest, institution, mailoutbox)

    def test_deactivate_user(self, caplog, client, mailoutbox, snapshot):
        institution = InstitutionFactory(name="DDETS 14")
        admin_membership = InstitutionMembershipFactory(institution=institution, is_admin=True)
        guest_membership = InstitutionMembershipFactory(institution=institution, is_admin=False)
        guest = guest_membership.user

        received_invitation = LaborInspectorInvitationFactory(email=guest.email, institution=institution)
        sent_invitation = LaborInspectorInvitationFactory(sender=guest, institution=institution)
        sent_invitation_to_other = LaborInspectorInvitationFactory(sender=guest)

        client.force_login(admin_membership.user)
        url = reverse("institutions_views:deactivate_member", kwargs={"public_id": guest.public_id})
        response = client.post(url)
        assert response.status_code == 302

        # User should be deactivated now
        guest_membership.refresh_from_db()
        assert guest_membership.is_active is False
        assert admin_membership.user_id == guest_membership.updated_by_id
        assert guest_membership.updated_at is not None
        assert (
            f"Expired 1 invitations to institutions.Institution {institution.pk} for user_id={guest.pk}."
        ) in caplog.messages
        assert (
            f"Expired 1 invitations to institutions.Institution {institution.pk} from user_id={guest.pk}."
        ) in caplog.messages
        assert (
            f"User {admin_membership.user_id} deactivated institutions.InstitutionMembership "
            f"of organization_id={institution.pk} for user_id={guest.pk} is_admin=False."
        ) in caplog.messages

        # User must have been notified of deactivation (we're human after all)
        [email] = mailoutbox
        assert f"[DEV] [Désactivation] Vous n'êtes plus membre de {institution.display_name}" == email.subject
        assert "Un administrateur vous a retiré d'une structure sur les emplois de l'inclusion" in email.body
        assert email.to == [guest_membership.user.email]
        assert email.body == snapshot
        received_invitation.refresh_from_db()
        assert received_invitation.has_expired is True
        sent_invitation.refresh_from_db()
        assert sent_invitation.has_expired is True
        sent_invitation_to_other.refresh_from_db()
        assert sent_invitation_to_other.has_expired is False

    def test_deactivate_user_from_another_organisation(self, client, mailoutbox):
        my_institution = InstitutionFactory()
        other_institution = InstitutionFactory()
        my_membership = InstitutionMembershipFactory(institution=my_institution, is_admin=True)
        other_membership = InstitutionMembershipFactory(institution=other_institution)

        client.force_login(my_membership.user)
        response = client.post(
            reverse(
                "institutions_views:deactivate_member",
                kwargs={"public_id": other_membership.user.public_id},
            ),
        )

        assert response.status_code == 404
        other_membership.refresh_from_db()
        assert other_membership.is_active is True

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_deactivate_inactive_member(self, client, method, mailoutbox):
        institution = InstitutionFactory()
        admin_membership = InstitutionMembershipFactory(institution=institution, is_admin=True)
        guest_membership = InstitutionMembershipFactory(institution=institution, is_active=False)

        client.force_login(admin_membership.user)
        request = getattr(client, method)
        response = request(
            reverse("institutions_views:deactivate_member", kwargs={"public_id": guest_membership.user.public_id})
        )
        assert response.status_code == 404
        guest_membership.refresh_from_db()
        assert guest_membership.is_active is False
        assert mailoutbox == []

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_deactivate_non_member(self, client, method, mailoutbox):
        institution = InstitutionFactory()
        admin_membership = InstitutionMembershipFactory(institution=institution, is_admin=True)
        other_user = LaborInspectorFactory()
        client.force_login(admin_membership.user)
        request = getattr(client, method)
        response = request(reverse("institutions_views:deactivate_member", kwargs={"public_id": other_user.public_id}))
        assert response.status_code == 404
        assert mailoutbox == []

    def test_deactivate_admin(self, caplog, client, mailoutbox):
        institution = InstitutionFactory()
        admin_membership = InstitutionMembershipFactory(institution=institution, is_admin=True)
        other_admin_membership = InstitutionMembershipFactory(institution=institution, is_admin=True)
        other_admin = other_admin_membership.user
        invitation = LaborInspectorInvitationFactory(email=other_admin.email, institution=institution)

        client.force_login(admin_membership.user)
        response = client.post(
            reverse("institutions_views:deactivate_member", kwargs={"public_id": other_admin.public_id})
        )

        assertRedirects(response, reverse("institutions_views:members"))
        other_admin_membership.refresh_from_db()
        assert other_admin_membership.is_active is False
        assert other_admin_membership.updated_by_id == admin_membership.user_id
        assert other_admin_membership.updated_at is not None
        assert (
            f"Expired 1 invitations to institutions.Institution {institution.pk} for user_id={other_admin.pk}."
        ) in caplog.messages
        assert (
            f"Expired 0 invitations to institutions.Institution {institution.pk} from user_id={other_admin.pk}."
        ) in caplog.messages
        assert (
            f"User {admin_membership.user_id} deactivated institutions.InstitutionMembership "
            f"of organization_id={institution.pk} for user_id={other_admin.pk} is_admin=True."
        ) in caplog.messages
        [email] = mailoutbox
        assert f"[DEV] [Désactivation] Vous n'êtes plus membre de {institution.display_name}" == email.subject
        assert "Un administrateur vous a retiré d'une structure sur les emplois de l'inclusion" in email.body
        assert email.to == [other_admin_membership.user.email]
        invitation.refresh_from_db()
        assert invitation.has_expired is True

    def test_remove_admin(self, client, mailoutbox):
        """
        Check the ability for an admin to remove another admin
        """
        institution = InstitutionWith2MembershipFactory()
        admin = institution.members.filter(institutionmembership__is_admin=True).first()
        guest = institution.members.filter(institutionmembership__is_admin=False).first()

        membership = guest.institutionmembership_set.first()
        membership.is_admin = True
        membership.save()
        assert guest in institution.active_admin_members

        client.force_login(admin)
        url = reverse(
            "institutions_views:update_admin_role", kwargs={"action": "remove", "public_id": guest.public_id}
        )

        # Redirection to confirm page
        response = client.get(url)
        assert response.status_code == 200

        # Confirm action
        response = client.post(url)
        assert response.status_code == 302

        institution.refresh_from_db()
        assert_set_admin_role_removal(guest, institution, mailoutbox)

    def test_suspicious_action(self, client):
        suspicious_action = "h4ckm3"
        institution = InstitutionFactory()
        admin_membership = InstitutionMembershipFactory(institution=institution, is_admin=True)
        client.force_login(admin_membership.user)

        response = client.get(
            reverse(
                "institutions_views:update_admin_role",
                kwargs={"action": suspicious_action, "public_id": admin_membership.user.public_id},
            )
        )
        assert response.status_code == 400
