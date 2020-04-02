from django.conf import settings
from django.core import mail
from django.test import TestCase

from itou.prescribers.factories import AuthorizedPrescriberOrganizationWithMembershipFactory
from itou.users.factories import PrescriberFactory


class ModelTest(TestCase):
    def test_new_signup_warning_email_to_existing_members(self):
        """
        Test `new_signup_warning_email_to_existing_members`.
        """
        authorized_organization = AuthorizedPrescriberOrganizationWithMembershipFactory()

        self.assertEqual(1, authorized_organization.members.count())
        user = authorized_organization.members.first()

        new_user = PrescriberFactory()
        message = authorized_organization.new_signup_warning_email_to_existing_members(new_user)
        message.send()

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Un nouvel utilisateur vient de rejoindre votre organisation", email.subject)
        self.assertIn("Si vous ne connaissez pas cette personne veuillez nous contacter", email.body)
        self.assertIn(new_user.first_name, email.body)
        self.assertIn(new_user.last_name, email.body)
        self.assertIn(new_user.email, email.body)
        self.assertIn(authorized_organization.display_name, email.body)
        self.assertIn(authorized_organization.siret, email.body)
        self.assertIn(authorized_organization.kind, email.body)
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(email.to[0], user.email)
