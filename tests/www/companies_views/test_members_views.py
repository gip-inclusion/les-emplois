import pytest
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from tests.common_apps.organizations.tests import assert_set_admin_role__creation, assert_set_admin_role__removal
from tests.companies.factories import (
    CompanyFactory,
    CompanyMembershipFactory,
    CompanyWith2MembershipsFactory,
)
from tests.utils.test import assert_previous_step


class TestMembers:
    MORE_ADMIN_MSG = "Nous vous recommandons de nommer plusieurs administrateurs"

    def test_members(self, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        client.force_login(user)
        url = reverse("companies_views:members")
        response = client.get(url)
        assert response.status_code == 200
        assert_previous_step(response, reverse("dashboard:index"))

    def test_active_members(self, client):
        company = CompanyFactory()
        active_member_active_user = CompanyMembershipFactory(company=company)
        active_member_inactive_user = CompanyMembershipFactory(company=company, user__is_active=False)
        inactive_member_active_user = CompanyMembershipFactory(company=company, is_active=False)
        inactive_member_inactive_user = CompanyMembershipFactory(
            company=company, is_active=False, user__is_active=False
        )

        client.force_login(active_member_active_user.user)
        url = reverse("companies_views:members")
        response = client.get(url)
        assert response.status_code == 200
        assert len(response.context["members"]) == 1
        assert active_member_active_user in response.context["members"]
        assert active_member_inactive_user not in response.context["members"]
        assert inactive_member_active_user not in response.context["members"]
        assert inactive_member_inactive_user not in response.context["members"]

    def test_members_admin_warning_one_user(self, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        client.force_login(user)
        url = reverse("companies_views:members")
        response = client.get(url)
        assertNotContains(response, self.MORE_ADMIN_MSG)

    def test_members_admin_warning_two_users(self, client):
        company = CompanyWith2MembershipsFactory()
        user = company.members.first()
        client.force_login(user)
        url = reverse("companies_views:members")
        response = client.get(url)
        assertContains(response, self.MORE_ADMIN_MSG)

        # Set all users admins
        company.memberships.update(is_admin=True)
        response = client.get(url)
        assertNotContains(response, self.MORE_ADMIN_MSG)

    def test_members_admin_warning_many_users(self, client):
        company = CompanyWith2MembershipsFactory()
        CompanyMembershipFactory(company=company, user__is_active=False)
        CompanyMembershipFactory(company=company, is_admin=False, user__is_active=False)
        user = company.members.first()
        client.force_login(user)
        url = reverse("companies_views:members")
        response = client.get(url)
        assertContains(response, self.MORE_ADMIN_MSG)


class TestUserMembershipDeactivation:
    def test_self_deactivation(self, client):
        """
        A user, even if admin, can't self-deactivate
        (must be done by another admin)
        """
        company = CompanyFactory(with_membership=True)
        admin = company.members.filter(companymembership__is_admin=True).first()
        memberships = admin.companymembership_set.all()
        membership = memberships.first()

        client.force_login(admin)
        url = reverse("companies_views:deactivate_member", kwargs={"user_id": admin.id})
        response = client.post(url)
        assert response.status_code == 403

        # Trying to change self membership is not allowed
        # but does not raise an error (does nothing)
        membership.refresh_from_db()
        assert membership.is_active

    def test_deactivate_user(self, client, mailoutbox):
        """
        Standard use case of user deactivation.
        Everything should be fine ...
        """
        company = CompanyWith2MembershipsFactory()
        admin = company.members.filter(companymembership__is_admin=True).first()
        guest = company.members.filter(companymembership__is_admin=False).first()

        membership = guest.companymembership_set.first()
        assert guest not in company.active_admin_members
        assert admin in company.active_admin_members

        client.force_login(admin)
        url = reverse("companies_views:deactivate_member", kwargs={"user_id": guest.id})
        response = client.post(url)
        assert response.status_code == 302

        # User should be deactivated now
        membership.refresh_from_db()
        assert not membership.is_active
        assert admin == membership.updated_by
        assert membership.updated_at is not None

        # Check mailbox
        # User must have been notified of deactivation (we're human after all)
        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert f"[DEV] [Désactivation] Vous n'êtes plus membre de {company.display_name}" == email.subject
        assert "Un administrateur vous a retiré d'une structure sur les emplois de l'inclusion" in email.body
        assert email.to[0] == guest.email

    def test_deactivate_with_no_perms(self, client):
        """
        Non-admin user can't change memberships
        """
        company = CompanyWith2MembershipsFactory()
        guest = company.members.filter(companymembership__is_admin=False).first()
        client.force_login(guest)
        url = reverse("companies_views:deactivate_member", kwargs={"user_id": guest.id})
        response = client.post(url)
        assert response.status_code == 403

    def test_user_with_no_company_left(self, client):
        """
        Former employer with no membership left must not be able to log in.
        They are still "active" technically speaking, so if they
        are activated/invited again, they will be able to log in.
        """
        company = CompanyWith2MembershipsFactory()
        admin = company.members.filter(companymembership__is_admin=True).first()
        guest = company.members.filter(companymembership__is_admin=False).first()

        client.force_login(admin)
        url = reverse("companies_views:deactivate_member", kwargs={"user_id": guest.id})
        response = client.post(url)
        assert response.status_code == 302
        client.logout()

        client.force_login(guest)
        url = reverse("dashboard:index")
        response = client.get(url)

        # should be redirected to logout
        assertRedirects(response, reverse("logout:warning", kwargs={"kind": "employer_no_company"}))

    def test_structure_selector(self, client):
        """
        Check that a deactivated member can't access the structure
        from the dashboard selector
        """
        company_2 = CompanyFactory(with_membership=True)
        guest = company_2.members.first()

        company_1 = CompanyWith2MembershipsFactory()
        admin = company_1.members.first()
        company_1.members.add(guest)

        memberships = guest.companymembership_set.all()
        assert len(memberships) == 2

        # Admin remove guest from structure
        client.force_login(admin)
        url = reverse("companies_views:deactivate_member", kwargs={"user_id": guest.id})
        response = client.post(url)
        assert response.status_code == 302
        client.logout()

        # guest must be able to login
        client.force_login(guest)
        url = reverse("dashboard:index")
        response = client.get(url)

        # Wherever guest lands should give a 200 OK
        assert response.status_code == 200

        # Check response context, only one company should remain
        assert len(response.context["request"].organizations) == 1


class TestCompanyAdminMembersManagement:
    def test_add_admin(self, client, mailoutbox):
        """
        Check the ability for an admin to add another admin to the company
        """
        company = CompanyWith2MembershipsFactory()
        admin = company.members.filter(companymembership__is_admin=True).first()
        guest = company.members.filter(companymembership__is_admin=False).first()

        client.force_login(admin)
        url = reverse("companies_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        # Redirection to confirm page
        response = client.get(url)
        assert response.status_code == 200

        # Confirm action
        response = client.post(url)
        assert response.status_code == 302

        company.refresh_from_db()
        assert_set_admin_role__creation(guest, company, mailoutbox)

    def test_remove_admin(self, client, mailoutbox):
        """
        Check the ability for an admin to remove another admin
        """
        company = CompanyWith2MembershipsFactory()
        admin = company.members.filter(companymembership__is_admin=True).first()
        guest = company.members.filter(companymembership__is_admin=False).first()

        membership = guest.companymembership_set.first()
        membership.is_admin = True
        membership.save()
        assert guest in company.active_admin_members

        client.force_login(admin)
        url = reverse("companies_views:update_admin_role", kwargs={"action": "remove", "user_id": guest.id})

        # Redirection to confirm page
        response = client.get(url)
        assert response.status_code == 200

        # Confirm action
        response = client.post(url)
        assert response.status_code == 302

        company.refresh_from_db()
        assert_set_admin_role__removal(guest, company, mailoutbox)

    def test_admin_management_permissions(self, client):
        """
        Non-admin users can't update admin members
        """
        company = CompanyWith2MembershipsFactory()
        admin = company.members.filter(companymembership__is_admin=True).first()
        guest = company.members.filter(companymembership__is_admin=False).first()

        client.force_login(guest)
        url = reverse("companies_views:update_admin_role", kwargs={"action": "remove", "user_id": admin.id})

        # Redirection to confirm page
        response = client.get(url)
        assert response.status_code == 403

        # Confirm action
        response = client.post(url)
        assert response.status_code == 403

        # Add self as admin with no privilege
        url = reverse("companies_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        response = client.get(url)
        assert response.status_code == 403

        response = client.post(url)
        assert response.status_code == 403

    def test_suspicious_action(self, client):
        """
        Test "suspicious" actions: action code not registered for use (even if admin)
        """
        suspicious_action = "h4ckm3"
        company = CompanyWith2MembershipsFactory()
        admin = company.members.filter(companymembership__is_admin=True).first()
        guest = company.members.filter(companymembership__is_admin=False).first()

        client.force_login(guest)
        # update: less test with RE_PATH
        with pytest.raises(NoReverseMatch):
            reverse("companies_views:update_admin_role", kwargs={"action": suspicious_action, "user_id": admin.id})
