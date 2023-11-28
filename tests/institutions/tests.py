from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from tests.institutions.factories import (
    InstitutionMembershipFactory,
    InstitutionWith2MembershipFactory,
    InstitutionWithMembershipFactory,
)
from tests.users.factories import ItouStaffFactory
from tests.utils.test import TestCase


class InstitutionModelTest(TestCase):
    def test_active_admin_members(self):
        """
        Test that if a user is admin of org1 and regular user
        of org2 he is not considered as admin of org2.
        """
        institution1 = InstitutionWithMembershipFactory()
        institution1_admin_user = institution1.members.first()
        institution2 = InstitutionWithMembershipFactory()
        institution2.members.add(institution1_admin_user)

        assert institution1_admin_user in institution1.active_admin_members
        assert institution1_admin_user not in institution2.active_admin_members

    def test_active_members(self):
        institution = InstitutionWith2MembershipFactory(membership2__is_active=False)
        active_user_with_active_membership = institution.members.first()
        active_user_with_inactive_membership = institution.members.last()
        inactive_user_with_active_membership = InstitutionMembershipFactory(
            institution=institution, user__is_active=False
        )

        assert active_user_with_active_membership in institution.active_members
        assert active_user_with_inactive_membership not in institution.active_members
        assert inactive_user_with_active_membership not in institution.active_members

        # Deactivate a membership
        active_user_with_active_membership.is_active = False
        active_user_with_active_membership.save()

        assert active_user_with_active_membership not in institution.active_members


def test_deactivate_last_admin(client):
    institution = InstitutionWithMembershipFactory(department="")
    membership = institution.memberships.first()
    assert membership.is_admin

    staff_user = ItouStaffFactory(is_superuser=True)
    client.force_login(staff_user)
    change_url = reverse("admin:institutions_institution_change", args=[institution.pk])
    response = client.get(change_url)
    assert response.status_code == 200

    response = client.post(
        change_url,
        data={
            "kind": institution.kind.value,
            "name": institution.name,
            "address_line_1": institution.address_line_1,
            "address_line_2": institution.address_line_2,
            "post_code": institution.post_code,
            "city": institution.city,
            "department": institution.department,
            "coords": "",
            "institutionmembership_set-TOTAL_FORMS": "2",
            "institutionmembership_set-INITIAL_FORMS": "1",
            "institutionmembership_set-MIN_NUM_FORMS": "0",
            "institutionmembership_set-MAX_NUM_FORMS": "1000",
            "institutionmembership_set-0-id": membership.pk,
            "institutionmembership_set-0-institution": institution.pk,
            "institutionmembership_set-0-user": membership.user.pk,
            # institutionmembership_set-0-is_admin is absent
            "_continue": "Enregistrer+et+continuer+les+modifications",
        },
    )
    assertRedirects(response, change_url, fetch_redirect_response=False)
    response = client.get(change_url)
    assertContains(
        response,
        (
            "Vous venez de supprimer le dernier administrateur de la structure. "
            "Les membres restants risquent de solliciter le support."
        ),
    )
