from django.test import TestCase
from django.utils import timezone

from itou.invitations.factories import (
    ExpiredInvitationFactory,
    InvitationFactory,
    SentInvitationFactory,
    SiaeSentInvitationFactory,
)
from itou.invitations.models import Invitation, SiaeStaffInvitation
from itou.users.factories import UserFactory


class InvitationModelTest(TestCase):
    def test_acceptance_link(self):
        invitation = SentInvitationFactory()
        self.assertIn(str(invitation.pk), invitation.acceptance_link)

        # Must be an absolute URL
        self.assertTrue(invitation.acceptance_link.startswith("http"))

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

    def test_get_model_from_string(self):
        invitation_type = Invitation.get_model_from_string("siae_staff")
        self.assertEqual(invitation_type, SiaeStaffInvitation)

        with self.assertRaises(TypeError):
            Invitation.get_model_from_string("wrong_type")

        with self.assertRaises(TypeError):
            Invitation.get_model_from_string(12)


class InvitationEmailsTest(TestCase):
    def test_send_invitation(self):
        invitation = SentInvitationFactory()
        email = invitation.email_invitation

        # Subject
        self.assertIn(invitation.sender.first_name.title(), email.subject)
        self.assertIn(invitation.sender.last_name, email.subject)

        # Body
        self.assertIn(invitation.first_name, email.body)
        self.assertIn(invitation.last_name, email.body)
        self.assertIn(invitation.acceptance_link, email.body)

        self.assertIn(str(invitation.expiration_date.day), email.body)

        # To
        self.assertIn(invitation.email, email.to)


class TestSiaeInvitation(TestCase):
    def test_add_member_to_siae(self):
        invitation = SiaeSentInvitationFactory(email="hey@you.com")
        user = UserFactory(email=invitation.email)
        siae_members = invitation.siae.members.count()
        invitation.add_invited_user_to_siae()
        siae_members_after = invitation.siae.members.count()
        self.assertEqual(siae_members + 1, siae_members_after)

        user.refresh_from_db()


class TestSiaeInvitationEmails(TestCase):
    def test_accepted_notif_siae_members(self):
        user = UserFactory()
        invitation = SiaeSentInvitationFactory(email=user.email)
        invitation.siae.members.add(user)
        email = invitation.email_accepted_notif_siae_members

        # Subject
        self.assertIn(invitation.first_name, email.subject)
        self.assertIn(invitation.last_name, email.subject)

        # Body
        self.assertIn(invitation.first_name, email.body)
        self.assertIn(invitation.last_name, email.body)
        self.assertIn(invitation.email, email.body)
        self.assertIn(invitation.sender.first_name, email.body)
        self.assertIn(invitation.sender.last_name, email.body)
        self.assertIn(invitation.siae.display_name, email.body)

        # To
        members = invitation.siae.members.exclude(email__in=[invitation.sender.email, invitation.email])
        for member in members:
            self.assertIn(member.email, email.to)

        self.assertNotIn(invitation.sender.email, email.to)
        self.assertNotIn(invitation.email, email.to)

    def test_accepted_notif_sender(self):
        invitation = SiaeSentInvitationFactory()
        email = invitation.email_accepted_notif_sender

        # Subject
        self.assertIn(invitation.first_name, email.subject)
        self.assertIn(invitation.last_name, email.subject)

        # Body
        self.assertIn(invitation.first_name, email.body)
        self.assertIn(invitation.last_name, email.body)
        self.assertIn(invitation.email, email.body)
        self.assertIn(invitation.siae.display_name, email.body)

        # To
        self.assertIn(invitation.sender.email, email.to)

    def test_email_invitation(self):
        invitation = SiaeSentInvitationFactory()
        email = invitation.email_invitation

        # Subject
        self.assertIn(invitation.siae.display_name, email.subject)

        # Body
        self.assertIn(invitation.first_name, email.body)
        self.assertIn(invitation.last_name, email.body)
        self.assertIn(invitation.acceptance_link, email.body)
        self.assertIn(invitation.siae.display_name, email.body)

        # To
        self.assertIn(invitation.email, email.to)
