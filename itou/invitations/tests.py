from django.template.defaultfilters import capfirst
from django.test import TestCase
from django.utils import timezone

from itou.invitations.factories import (
    ExpiredSiaeStaffInvitationFactory,
    PrescriberWithOrgSentInvitationFactory,
    SentSiaeStaffInvitationFactory,
    SiaeStaffInvitationFactory,
)
from itou.invitations.models import InvitationAbstract, SiaeStaffInvitation
from itou.users.factories import UserFactory


class SiaeStaffInvitationQuerySetTest(TestCase):
    def test_pending(self):

        # Create some non-expired invitations.
        invitation1 = SentSiaeStaffInvitationFactory()
        invitation2 = SentSiaeStaffInvitationFactory()
        invitation3 = SentSiaeStaffInvitationFactory()

        # Add one expired invitation.
        invitation4 = ExpiredSiaeStaffInvitationFactory()

        pending_invitations = SiaeStaffInvitation.objects.pending()

        self.assertEqual(3, pending_invitations.count())
        self.assertIn(invitation1.pk, pending_invitations.values_list("pk", flat=True))
        self.assertIn(invitation2.pk, pending_invitations.values_list("pk", flat=True))
        self.assertIn(invitation3.pk, pending_invitations.values_list("pk", flat=True))

        self.assertNotIn(invitation4.pk, pending_invitations.values_list("pk", flat=True))


class InvitationModelTest(TestCase):
    def test_acceptance_link(self):
        invitation = SentSiaeStaffInvitationFactory()
        self.assertIn(str(invitation.pk), invitation.acceptance_link)

        # Must be an absolute URL
        self.assertTrue(invitation.acceptance_link.startswith("http"))

    def has_expired(self):
        invitation = ExpiredSiaeStaffInvitationFactory()
        self.assertTrue(invitation.has_expired)

        invitation = SentSiaeStaffInvitationFactory()
        self.assertFalse(invitation.has_expired)

    def test_can_be_accepted(self):
        invitation = ExpiredSiaeStaffInvitationFactory()
        self.assertFalse(invitation.can_be_accepted)

        invitation = SiaeStaffInvitationFactory(sent_at=timezone.now())
        self.assertFalse(invitation.can_be_accepted)

        invitation = SentSiaeStaffInvitationFactory(accepted=True)
        self.assertFalse(invitation.can_be_accepted)

        invitation = SentSiaeStaffInvitationFactory()
        self.assertTrue(invitation.can_be_accepted)

    def test_extend_expiration_date(self):
        invitation = ExpiredSiaeStaffInvitationFactory()
        self.assertTrue(invitation.has_expired)
        invitation.extend_expiration_date()
        self.assertFalse(invitation.has_expired)

    def test_get_model_from_string(self):
        invitation_type = InvitationAbstract.get_model_from_string("siae_staff")
        self.assertEqual(invitation_type, SiaeStaffInvitation)

        with self.assertRaises(TypeError):
            InvitationAbstract.get_model_from_string("wrong_type")

        with self.assertRaises(TypeError):
            InvitationAbstract.get_model_from_string(12)


class InvitationEmailsTest(TestCase):
    def test_send_invitation(self):
        invitation = SentSiaeStaffInvitationFactory()
        email = invitation.email_invitation

        # Subject
        self.assertIn(capfirst(invitation.sender.first_name), email.subject)
        self.assertIn(capfirst(invitation.sender.last_name), email.subject)

        # Body
        self.assertIn(capfirst(invitation.first_name), email.body)
        self.assertIn(capfirst(invitation.last_name), email.body)
        self.assertIn(invitation.acceptance_link, email.body)

        self.assertIn(str(invitation.expiration_date.day), email.body)

        # To
        self.assertIn(invitation.email, email.to)


################################################################
###################### PrescribersWithOrg ######################
################################################################


class TestPrescriberWithOrgInvitation(TestCase):
    def test_add_member_to_organization(self):
        invitation = PrescriberWithOrgSentInvitationFactory(email="hey@you.com")
        UserFactory(email=invitation.email)
        org_members = invitation.organization.members.count()
        invitation.add_invited_user_to_organization()
        org_members_after = invitation.organization.members.count()
        self.assertEqual(org_members + 1, org_members_after)


class TestPrescriberWithOrgInvitationEmails(TestCase):
    def test_accepted_notif_sender(self):
        invitation = PrescriberWithOrgSentInvitationFactory()
        email = invitation.email_accepted_notif_sender

        # Subject
        self.assertIn(capfirst(invitation.first_name), email.subject)
        self.assertIn(capfirst(invitation.last_name), email.subject)

        # Body
        self.assertIn(capfirst(invitation.first_name), email.body)
        self.assertIn(capfirst(invitation.last_name), email.body)
        self.assertIn(invitation.email, email.body)
        self.assertIn(invitation.organization.display_name, email.body)

        # To
        self.assertIn(invitation.sender.email, email.to)

    def test_email_invitation(self):
        invitation = PrescriberWithOrgSentInvitationFactory()
        email = invitation.email_invitation

        # Subject
        self.assertIn(invitation.organization.display_name, email.subject)

        # Body
        self.assertIn(capfirst(invitation.first_name), email.body)
        self.assertIn(capfirst(invitation.last_name), email.body)
        self.assertIn(invitation.acceptance_link, email.body)
        self.assertIn(invitation.organization.display_name, email.body)

        # To
        self.assertIn(invitation.email, email.to)


class TestSiaeInvitation(TestCase):
    def test_add_member_to_siae(self):
        invitation = SentSiaeStaffInvitationFactory(email="hey@you.com")
        UserFactory(email=invitation.email)
        siae_members = invitation.siae.members.count()
        invitation.add_invited_user_to_siae()
        siae_members_after = invitation.siae.members.count()
        self.assertEqual(siae_members + 1, siae_members_after)


class TestSiaeInvitationEmails(TestCase):
    def test_accepted_notif_sender(self):
        invitation = SentSiaeStaffInvitationFactory()
        email = invitation.email_accepted_notif_sender

        # Subject
        self.assertIn(capfirst(invitation.first_name), email.subject)
        self.assertIn(capfirst(invitation.last_name), email.subject)

        # Body
        self.assertIn(capfirst(invitation.first_name), email.body)
        self.assertIn(capfirst(invitation.last_name), email.body)
        self.assertIn(invitation.email, email.body)
        self.assertIn(invitation.siae.display_name, email.body)

        # To
        self.assertIn(invitation.sender.email, email.to)

    def test_email_invitation(self):
        invitation = SentSiaeStaffInvitationFactory()
        email = invitation.email_invitation

        # Subject
        self.assertIn(invitation.siae.display_name, email.subject)

        # Body
        self.assertIn(capfirst(invitation.first_name), email.body)
        self.assertIn(capfirst(invitation.last_name), email.body)
        self.assertIn(invitation.acceptance_link, email.body)
        self.assertIn(invitation.siae.display_name, email.body)

        # To
        self.assertIn(invitation.email, email.to)
