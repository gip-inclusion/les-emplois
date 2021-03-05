from django.core.exceptions import ValidationError
from django.test import TestCase

from itou.prescribers.factories import (
    PrescriberOrganizationFactory,
    PrescriberOrganizationWith2MembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from itou.prescribers.models import PrescriberOrganization


class ModelTest(TestCase):
    def test_clean_siret(self):
        """
        Test that a SIRET number is required only for non-PE organizations.
        """
        org = PrescriberOrganizationFactory.build(siret="", kind=PrescriberOrganization.Kind.PE)
        org.clean_siret()
        with self.assertRaises(ValidationError):
            org = PrescriberOrganizationFactory.build(siret="", kind=PrescriberOrganization.Kind.CAP_EMPLOI)
            org.clean_siret()

    def test_clean_code_safir_pole_emploi(self):
        """
        Test that a code SAFIR can only be set for PE agencies.
        """
        org = PrescriberOrganizationFactory.build(code_safir_pole_emploi="12345", kind=PrescriberOrganization.Kind.PE)
        org.clean_code_safir_pole_emploi()
        with self.assertRaises(ValidationError):
            org = PrescriberOrganizationFactory.build(
                code_safir_pole_emploi="12345", kind=PrescriberOrganization.Kind.CAP_EMPLOI
            )
            org.clean_code_safir_pole_emploi()

    def test_has_pending_authorization_proof(self):

        org = PrescriberOrganizationFactory(
            kind=PrescriberOrganization.Kind.OTHER,
            authorization_status=PrescriberOrganization.AuthorizationStatus.NOT_SET,
        )
        self.assertTrue(org.has_pending_authorization())
        self.assertTrue(org.has_pending_authorization_proof())

        org = PrescriberOrganizationFactory(
            kind=PrescriberOrganization.Kind.CAP_EMPLOI,
            authorization_status=PrescriberOrganization.AuthorizationStatus.NOT_SET,
        )
        self.assertTrue(org.has_pending_authorization())
        self.assertFalse(org.has_pending_authorization_proof())

    def test_active_admin_members(self):
        """
        Test that if a user is admin of org1 and regular user
        of org2 it does not get considered as admin of org2.
        """
        organization1 = PrescriberOrganizationWithMembershipFactory()
        organization1_admin_user = organization1.active_admin_members.get()
        organization2 = PrescriberOrganizationWithMembershipFactory()
        organization2.members.add(organization1_admin_user)

        self.assertEqual(organization1.members.count(), 1)
        self.assertEqual(organization1.active_members.count(), 1)
        self.assertEqual(organization1.active_admin_members.count(), 1)

        self.assertEqual(organization2.members.count(), 2)
        self.assertEqual(organization2.active_members.count(), 2)
        self.assertEqual(organization2.active_admin_members.count(), 1)

    def test_active_member_with_many_memberships(self):
        organization1 = PrescriberOrganizationWith2MembershipFactory(membership2__is_active=False)
        user = organization1.members.filter(prescribermembership__is_admin=False).first()
        organization2 = PrescriberOrganizationWith2MembershipFactory()
        organization2.members.add(user)

        self.assertFalse(user in organization1.active_members)
        self.assertEqual(organization1.members.count(), 2)
        self.assertEqual(organization1.active_members.count(), 1)
        self.assertEqual(organization2.members.count(), 3)
        self.assertEqual(organization2.active_members.count(), 3)
