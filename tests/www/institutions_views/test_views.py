from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from tests.common_apps.organizations.tests import assert_set_admin_role__creation, assert_set_admin_role__removal
from tests.institutions.factories import (
    InstitutionFactory,
    InstitutionMembershipFactory,
    InstitutionWith2MembershipFactory,
    InstitutionWithMembershipFactory,
)


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
        url = reverse("institutions_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        # Redirection to confirm page
        response = client.get(url)
        assert response.status_code == 200

        # Confirm action
        response = client.post(url)
        assert response.status_code == 302

        institution.refresh_from_db()
        assert_set_admin_role__creation(guest, institution, mailoutbox)

    def test_deactivate_user(self, client, mailoutbox, snapshot):
        institution = InstitutionFactory(name="DDETS 14")
        admin_membership = InstitutionMembershipFactory(institution=institution, is_admin=True)
        guest_membership = InstitutionMembershipFactory(institution=institution, is_admin=False)
        guest_id = guest_membership.user_id

        client.force_login(admin_membership.user)
        url = reverse("institutions_views:deactivate_member", kwargs={"user_id": guest_id})
        response = client.post(url)
        assert response.status_code == 302

        # User should be deactivated now
        guest_membership.refresh_from_db()
        assert guest_membership.is_active is False
        assert admin_membership.user_id == guest_membership.updated_by_id
        assert guest_membership.updated_at is not None

        # User must have been notified of deactivation (we're human after all)
        [email] = mailoutbox
        assert f"[DEV] [Désactivation] Vous n'êtes plus membre de {institution.display_name}" == email.subject
        assert "Un administrateur vous a retiré d'une structure sur les emplois de l'inclusion" in email.body
        assert email.to == [guest_membership.user.email]
        assert email.body == snapshot

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
        url = reverse("institutions_views:update_admin_role", kwargs={"action": "remove", "user_id": guest.id})

        # Redirection to confirm page
        response = client.get(url)
        assert response.status_code == 200

        # Confirm action
        response = client.post(url)
        assert response.status_code == 302

        institution.refresh_from_db()
        assert_set_admin_role__removal(guest, institution, mailoutbox)
