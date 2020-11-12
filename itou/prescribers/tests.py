from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase

from itou.prescribers.factories import (
    AuthorizedPrescriberOrganizationWithMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from itou.prescribers.models import PrescriberOrganization
from itou.users.factories import PrescriberFactory


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

    def test_new_signup_warning_email_to_existing_members(self):
        authorized_organization = AuthorizedPrescriberOrganizationWithMembershipFactory()

        self.assertEqual(1, authorized_organization.members.count())
        user = authorized_organization.members.first()

        new_user = PrescriberFactory()
        message = authorized_organization.new_signup_warning_email_to_existing_members(new_user)
        message.send()

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Un nouvel utilisateur vient de rejoindre votre organisation", email.subject)
        self.assertIn("Si cette personne n'est pas un collaborateur ou une collaboratrice", email.body)
        self.assertIn(new_user.first_name, email.body)
        self.assertIn(new_user.last_name, email.body)
        self.assertIn(new_user.email, email.body)
        self.assertIn(authorized_organization.display_name, email.body)
        self.assertIn(authorized_organization.siret, email.body)
        self.assertIn(authorized_organization.kind, email.body)
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(email.to[0], user.email)

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
