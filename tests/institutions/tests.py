import pytest
from django.db import IntegrityError, transaction
from django.forms import ValidationError
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from tests.common_apps.organizations.tests import assert_set_admin_role__creation, assert_set_admin_role__removal
from tests.institutions.factories import (
    InstitutionFactory,
    InstitutionMembershipFactory,
    InstitutionWith2MembershipFactory,
    InstitutionWithMembershipFactory,
)
from tests.users.factories import LaborInspectorFactory, PrescriberFactory
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

    def test_add_or_activate_member(self):
        institution = InstitutionFactory()
        assert 0 == institution.members.count()
        admin_user = LaborInspectorFactory()
        institution.add_or_activate_member(admin_user)
        assert 1 == institution.memberships.count()
        assert institution.memberships.get(user=admin_user).is_admin

        other_user = LaborInspectorFactory()
        institution.add_or_activate_member(other_user)
        assert 2 == institution.memberships.count()
        assert not institution.memberships.get(user=other_user).is_admin
        assert institution.memberships.get(user=other_user).is_active

        institution.memberships.filter(user=other_user).update(is_active=False)
        institution.add_or_activate_member(other_user)
        assert institution.memberships.get(user=other_user).is_active

        wrong_kind_user = PrescriberFactory()
        with pytest.raises(ValidationError):
            institution.add_or_activate_member(wrong_kind_user)


def test_deactivate_last_admin(admin_client):
    institution = InstitutionWithMembershipFactory(department="")
    membership = institution.memberships.first()
    assert membership.is_admin

    change_url = reverse("admin:institutions_institution_change", args=[institution.pk])
    response = admin_client.get(change_url)
    assert response.status_code == 200

    response = admin_client.post(
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
    response = admin_client.get(change_url)
    assertContains(
        response,
        (
            "Vous venez de supprimer le dernier administrateur de la structure. "
            "Les membres restants risquent de solliciter le support."
        ),
    )

    assert_set_admin_role__removal(membership.user, institution)


def test_delete_admin(admin_client):
    institution = InstitutionWithMembershipFactory(department="")
    membership = institution.memberships.first()
    assert membership.is_admin

    change_url = reverse("admin:institutions_institution_change", args=[institution.pk])
    response = admin_client.get(change_url)
    assert response.status_code == 200

    response = admin_client.post(
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
            "institutionmembership_set-0-is_admin": "on",
            "institutionmembership_set-0-DELETE": "on",
            "_continue": "Enregistrer+et+continuer+les+modifications",
        },
    )
    assertRedirects(response, change_url, fetch_redirect_response=False)
    response = admin_client.get(change_url)

    assert_set_admin_role__removal(membership.user, institution)


def test_add_admin(admin_client):
    institution = InstitutionWithMembershipFactory(department="")
    membership = institution.memberships.first()
    labor_inspector = LaborInspectorFactory()
    assert membership.is_admin

    change_url = reverse("admin:institutions_institution_change", args=[institution.pk])
    response = admin_client.get(change_url)
    assert response.status_code == 200

    response = admin_client.post(
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
            "institutionmembership_set-0-is_admin": "on",
            "institutionmembership_set-1-institution": institution.pk,
            "institutionmembership_set-1-user": labor_inspector.pk,
            "institutionmembership_set-1-is_admin": "on",
            "_continue": "Enregistrer+et+continuer+les+modifications",
        },
    )
    assertRedirects(response, change_url, fetch_redirect_response=False)
    response = admin_client.get(change_url)

    assert_set_admin_role__creation(labor_inspector, institution)


@pytest.mark.parametrize(
    "kind",
    [
        InstitutionKind.DDETS_GEIQ,
        InstitutionKind.DDETS_IAE,
        InstitutionKind.DDETS_LOG,
    ],
)
def test_unique_ddets_per_department_constraint(kind):
    first_institution = InstitutionFactory(kind=kind)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Institution.objects.create(kind=kind, department=first_institution.department)
