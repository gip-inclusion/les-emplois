from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from django.utils.http import urlsafe_base64_decode

from itou.invitations.factories import ExpiredInvitationFactory, InvitationFactory, SentInvitationFactory
from itou.invitations.models import Invitation


BASE_URL = "http://testserver"


class InvitationModelTest(TestCase):
    def test_acceptance_link(self):
        invitation = SentInvitationFactory()
        acceptance_link = invitation.acceptance_link(base_url=BASE_URL)
        self.assertIn(str(invitation.pk), acceptance_link)

        # Must be an absolute URL
        self.assertTrue(acceptance_link.startswith("http"))

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

    def test_extend_expiration_date(self):
        invitation = ExpiredInvitationFactory()
        self.assertTrue(invitation.has_expired)
        invitation.extend_expiration_date()
        self.assertFalse(invitation.has_expired)


class InvitationEmailsTest(TestCase):
    def test_send_invitation(self):
        invitation = SentInvitationFactory()
        email = invitation.email_invitation(acceptance_link_base_url=BASE_URL)

        # Subject
        self.assertIn(invitation.sender.first_name, email.subject)
        self.assertIn(invitation.sender.last_name, email.subject)

        # Body
        self.assertIn(invitation.first_name, email.body)
        self.assertIn(invitation.last_name, email.body)
        self.assertIn(invitation.acceptance_link(base_url=BASE_URL), email.body)

        # To
        self.assertIn(invitation.email, email.to)

    def test_accepted_notif_sender(self):
        invitation = SentInvitationFactory()
        email = invitation.email_accepted_notif_sender

        # Subject
        self.assertIn(invitation.first_name, email.subject)
        self.assertIn(invitation.last_name, email.subject)

        # Body
        self.assertIn(invitation.first_name, email.body)
        self.assertIn(invitation.last_name, email.body)
        self.assertIn(invitation.email, email.body)

        # To
        self.assertIn(invitation.sender.email, email.to)
