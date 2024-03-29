from django.urls import reverse

from tests.common_apps.organizations.tests import assert_set_admin_role__creation, assert_set_admin_role__removal
from tests.institutions.factories import (
    InstitutionFactory,
    InstitutionMembershipFactory,
    InstitutionWith2MembershipFactory,
    InstitutionWithMembershipFactory,
)
from tests.utils.test import TestCase


# TODO: convert this to pytest
class MembersTest(TestCase):
    MORE_ADMIN_MSG = "Nous vous recommandons de nommer plusieurs administrateurs"

    def test_members(self):
        institution = InstitutionWithMembershipFactory()
        user = institution.members.first()
        self.client.force_login(user)
        url = reverse("institutions_views:members")
        response = self.client.get(url)
        assert response.status_code == 200

    def test_active_members(self):
        institution = InstitutionFactory()
        active_member_active_user = InstitutionMembershipFactory(institution=institution)
        active_member_inactive_user = InstitutionMembershipFactory(institution=institution, user__is_active=False)
        inactive_member_active_user = InstitutionMembershipFactory(institution=institution, is_active=False)
        inactive_member_inactive_user = InstitutionMembershipFactory(
            institution=institution, is_active=False, user__is_active=False
        )

        self.client.force_login(active_member_active_user.user)
        url = reverse("institutions_views:members")
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.context["members"]) == 1
        assert active_member_active_user in response.context["members"]
        assert active_member_inactive_user not in response.context["members"]
        assert inactive_member_active_user not in response.context["members"]
        assert inactive_member_inactive_user not in response.context["members"]

    def test_members_admin_warning_one_user(self):
        institution = InstitutionWithMembershipFactory()
        user = institution.members.first()
        self.client.force_login(user)
        url = reverse("institutions_views:members")
        response = self.client.get(url)
        self.assertNotContains(response, self.MORE_ADMIN_MSG)

    def test_members_admin_warning_two_users(self):
        institution = InstitutionWith2MembershipFactory()
        user = institution.members.first()
        self.client.force_login(user)
        url = reverse("institutions_views:members")
        response = self.client.get(url)
        self.assertContains(response, self.MORE_ADMIN_MSG)

        # Set all users admins
        institution.memberships.update(is_admin=True)
        response = self.client.get(url)
        self.assertNotContains(response, self.MORE_ADMIN_MSG)

    def test_members_admin_warning_many_users(self):
        institution = InstitutionWith2MembershipFactory()
        InstitutionMembershipFactory(institution=institution, user__is_active=False)
        InstitutionMembershipFactory(institution=institution, is_admin=False, user__is_active=False)
        user = institution.members.first()
        self.client.force_login(user)
        url = reverse("institutions_views:members")
        response = self.client.get(url)
        self.assertContains(response, self.MORE_ADMIN_MSG)

    def test_add_admin(self):
        """
        Check the ability for an admin to add another admin to the company
        """
        institution = InstitutionWith2MembershipFactory()
        admin = institution.members.filter(institutionmembership__is_admin=True).first()
        guest = institution.members.filter(institutionmembership__is_admin=False).first()

        self.client.force_login(admin)
        url = reverse("institutions_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        # Redirection to confirm page
        response = self.client.get(url)
        assert response.status_code == 200

        # Confirm action
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url)
        assert response.status_code == 302

        institution.refresh_from_db()
        assert_set_admin_role__creation(user=guest, organization=institution)

    def test_remove_admin(self):
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

        self.client.force_login(admin)
        url = reverse("institutions_views:update_admin_role", kwargs={"action": "remove", "user_id": guest.id})

        # Redirection to confirm page
        response = self.client.get(url)
        assert response.status_code == 200

        # Confirm action
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url)
        assert response.status_code == 302

        institution.refresh_from_db()
        assert_set_admin_role__removal(user=guest, organization=institution)
