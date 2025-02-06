from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.forms import ValidationError
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertQuerySetEqual, assertRedirects

from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.invitations.models import LaborInspectorInvitation
from tests.common_apps.organizations.tests import assert_set_admin_role__creation, assert_set_admin_role__removal
from tests.institutions.factories import (
    InstitutionFactory,
    InstitutionMembershipFactory,
    InstitutionWith2MembershipFactory,
    InstitutionWithMembershipFactory,
)
from tests.invitations.factories import LaborInspectorInvitationFactory
from tests.users.factories import LaborInspectorFactory, PrescriberFactory


class TestInstitutionModel:
    def test_active_admin_members(self):
        """
        Test that if a user is admin of org1 and regular user
        of org2 he is not considered as admin of org2.
        """
        institution1 = InstitutionWithMembershipFactory(department="01")
        institution1_admin_user = institution1.members.first()
        institution2 = InstitutionWithMembershipFactory(department="02")
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

    def test_add_or_activate_membership(self, caplog):
        institution = InstitutionFactory()
        assert 0 == institution.members.count()
        admin_user = LaborInspectorFactory()
        institution.add_or_activate_membership(admin_user)
        assert 1 == institution.memberships.count()
        assert institution.memberships.get(user=admin_user).is_admin
        assert (
            f"Expired 0 invitations to institutions.Institution {institution.pk} for user_id={admin_user.pk}."
            in caplog.messages
        )
        assert (
            f"Creating institutions.InstitutionMembership of organization_id={institution.pk} "
            f"for user_id={admin_user.pk} is_admin=True."
        ) in caplog.messages

        other_user = LaborInspectorFactory()
        invit1, invit2 = LaborInspectorInvitationFactory.create_batch(
            2, email=other_user.email, institution=institution, sender=admin_user
        )
        invit_expired = LaborInspectorInvitationFactory(
            email=other_user.email,
            institution=institution,
            sender=admin_user,
            sent_at=timezone.now() - timedelta(days=365),
        )
        invit_other = LaborInspectorInvitationFactory(email=other_user.email)
        institution.add_or_activate_membership(other_user)
        assert 2 == institution.memberships.count()
        assert not institution.memberships.get(user=other_user).is_admin
        assert institution.memberships.get(user=other_user).is_active
        assert (
            f"Expired 2 invitations to institutions.Institution {institution.pk} for user_id={other_user.pk}."
        ) in caplog.messages
        assert (
            f"Creating institutions.InstitutionMembership of organization_id={institution.pk} "
            f"for user_id={other_user.pk} is_admin=False."
        ) in caplog.messages
        assertQuerySetEqual(
            LaborInspectorInvitation.objects.all(),
            [
                (invit1.pk, institution.pk, admin_user.pk, other_user.email, 0),
                (invit2.pk, institution.pk, admin_user.pk, other_user.email, 0),
                (invit_expired.pk, institution.pk, admin_user.pk, other_user.email, 14),
                (invit_other.pk, invit_other.institution_id, invit_other.sender_id, other_user.email, 14),
            ],
            transform=lambda x: (
                x.pk,
                x.institution_id,
                x.sender_id,
                x.email,
                x.validity_days,
            ),
            ordered=False,
        )

        institution.memberships.filter(user=other_user).update(is_active=False, is_admin=True)
        invit = LaborInspectorInvitationFactory(email=other_user.email, institution=institution, sender=admin_user)
        institution.add_or_activate_membership(other_user)
        assert institution.memberships.get(user=other_user).is_active
        assert institution.memberships.get(user=other_user).is_admin is False
        assert (
            f"Expired 1 invitations to institutions.Institution {institution.pk} for user_id={other_user.pk}."
            in caplog.messages
        )
        assert (
            f"Reactivating institutions.InstitutionMembership of organization_id={institution.pk} "
            f"for user_id={other_user.pk} is_admin=False."
        ) in caplog.messages
        invit.refresh_from_db()
        assert invit.has_expired is True

        wrong_kind_user = PrescriberFactory()
        with pytest.raises(ValidationError):
            institution.add_or_activate_membership(wrong_kind_user)


def test_deactivate_last_admin(admin_client, mailoutbox):
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

    assert_set_admin_role__removal(membership.user, institution, mailoutbox)


def test_delete_admin(admin_client, caplog, mailoutbox):
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

    assert membership.user not in institution.active_admin_members
    [email] = mailoutbox
    assert f"[DEV] [Désactivation] Vous n'êtes plus membre de {institution.display_name}" == email.subject
    assert "Un administrateur vous a retiré d'une structure" in email.body
    assert email.to == [membership.user.email]
    assert (
        f"User {admin_client.session['_auth_user_id']} deactivated institutions.InstitutionMembership "
        f"of organization_id={institution.pk} for user_id={membership.user_id} is_admin=True."
    ) in caplog.messages


def test_add_admin(admin_client, caplog, mailoutbox):
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

    assert_set_admin_role__creation(labor_inspector, institution, mailoutbox)
    assert (
        f"Creating institutions.InstitutionMembership of organization_id={institution.pk} "
        f"for user_id={labor_inspector.pk} is_admin=True."
    ) in caplog.messages


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
