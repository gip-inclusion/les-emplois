from django.test import TestCase
from django.utils import timezone
from django.utils.http import urlsafe_base64_decode

from itou.invitations.factories import ExpiredInvitationFactory, InvitationFactory, SentInvitationFactory
from itou.invitations.models import Invitation


class InvitationModelTest(TestCase):
    def test_acceptance_link(self):
        invitation = SentInvitationFactory()
        self.assertIn(str(invitation.pk), invitation.acceptance_link)

    def has_expired(self):
        invitation = ExpiredInvitationFactory()
        self.assertTrue(invitation.has_expired)

        invitation = SentInvitationFactory()
        self.assertFalse(invitation.has_expired)

    def test_can_be_accepted(self):
        invitation = ExpiredInvitationFactory()
        self.assertFalse(invitation.can_be_accepted)

        invitation = InvitationFactory(sent_at=timezone.now())
        self.assertFalse(invitation.can_be_accepted)

        invitation = SentInvitationFactory(accepted=True)
        self.assertFalse(invitation.can_be_accepted)

        invitation = SentInvitationFactory()
        self.assertTrue(invitation.can_be_accepted)


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
