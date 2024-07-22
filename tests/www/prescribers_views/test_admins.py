import pytest
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch

from tests.common_apps.organizations.tests import assert_set_admin_role__creation, assert_set_admin_role__removal
from tests.prescribers.factories import PrescriberOrganizationWith2MembershipFactory


class TestPrescribersOrganizationAdminMembersManagement:
    def test_add_admin(self, client):
        """
        Check the ability for an admin to add another admin to the organization
        """
        organization = PrescriberOrganizationWith2MembershipFactory()
        admin = organization.members.filter(prescribermembership__is_admin=True).first()
        guest = organization.members.filter(prescribermembership__is_admin=False).first()

        client.force_login(admin)
        url = reverse("prescribers_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        # Redirection to confirm page
        response = client.get(url)
        assert response.status_code == 200

        # Confirm action
        response = client.post(url)
        assert response.status_code == 302

        organization.refresh_from_db()
        assert_set_admin_role__creation(user=guest, organization=organization)

    def test_remove_admin(self, client):
        """
        Check the ability for an admin to remove another admin
        """
        organization = PrescriberOrganizationWith2MembershipFactory()
        admin = organization.members.filter(prescribermembership__is_admin=True).first()
        guest = organization.members.filter(prescribermembership__is_admin=False).first()

        membership = guest.prescribermembership_set.first()
        membership.is_admin = True
        membership.save()
        assert guest in organization.active_admin_members

        client.force_login(admin)
        url = reverse("prescribers_views:update_admin_role", kwargs={"action": "remove", "user_id": guest.id})

        # Redirection to confirm page
        response = client.get(url)
        assert response.status_code == 200

        # Confirm action
        response = client.post(url)
        assert response.status_code == 302

        organization.refresh_from_db()
        assert_set_admin_role__removal(user=guest, organization=organization)

    def test_admin_management_permissions(self, client):
        """
        Non-admin users can't update admin members
        """
        organization = PrescriberOrganizationWith2MembershipFactory()
        admin = organization.members.filter(prescribermembership__is_admin=True).first()
        guest = organization.members.filter(prescribermembership__is_admin=False).first()

        client.force_login(guest)
        url = reverse("prescribers_views:update_admin_role", kwargs={"action": "remove", "user_id": admin.id})

        # Redirection to confirm page
        response = client.get(url)
        assert response.status_code == 403

        # Confirm action
        response = client.post(url)
        assert response.status_code == 403

        # Add self as admin with no privilege
        url = reverse("prescribers_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        response = client.get(url)
        assert response.status_code == 403

        response = client.post(url)
        assert response.status_code == 403

    def test_suspicious_action(self, client):
        """
        Test "suspicious" actions: action code not registered for use (even if admin)
        """
        suspicious_action = "h4ckm3"
        organization = PrescriberOrganizationWith2MembershipFactory()
        admin = organization.members.filter(prescribermembership__is_admin=True).first()
        guest = organization.members.filter(prescribermembership__is_admin=False).first()

        client.force_login(guest)

        # update: possible actions are now filtered via RE_PATH in urls.py
        with pytest.raises(NoReverseMatch):
            reverse("prescribers_views:update_admin_role", kwargs={"action": suspicious_action, "user_id": admin.id})
