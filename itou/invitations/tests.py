from django.test import TestCase
from django.utils.http import urlsafe_base64_decode

from itou.invitations.factories import SentInvitationFactory
from itou.invitations.models import Invitation


class InvitationModelTest(TestCase):
    def setUp(self):
        self.invitation = SentInvitationFactory()

    def test_acceptance_link(self):
        self.assertIn(str(self.invitation.pk), self.invitation.acceptance_link)


class InvitationEmailsTest(TestCase):
    def setUp(self):
        self.invitation = SentInvitationFactory()

    def test_accepted_notif_sender(self):
        email = self.invitation.email_accepted_notif_sender

        # Subject
        self.assertIn(self.invitation.first_name, email.subject)
        self.assertIn(self.invitation.last_name, email.subject)

        # Body
        self.assertIn(self.invitation.first_name, email.body)
        self.assertIn(self.invitation.last_name, email.body)
        self.assertIn(self.invitation.email, email.body)

        # To
        self.assertIn(self.invitation.sender.email, email.to)
