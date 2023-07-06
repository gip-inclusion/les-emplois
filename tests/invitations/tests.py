import pytest
from django.template.defaultfilters import capfirst
from django.test import SimpleTestCase
from django.utils import timezone

from itou.invitations.models import InvitationAbstract, SiaeStaffInvitation
from tests.invitations.factories import (
    ExpiredSiaeStaffInvitationFactory,
    PrescriberWithOrgSentInvitationFactory,
    SentSiaeStaffInvitationFactory,
    SiaeStaffInvitationFactory,
)
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.siaes.factories import SiaeMembershipFactory
from tests.users.factories import PrescriberFactory, SiaeStaffFactory
from tests.utils.test import TestCase


class SiaeStaffInvitationQuerySetTest(TestCase):
    def test_pending(self):

        # Create some non-expired invitations.
        invitation1 = SentSiaeStaffInvitationFactory()
        invitation2 = SentSiaeStaffInvitationFactory()
        invitation3 = SentSiaeStaffInvitationFactory()

        # Add one expired invitation.
        invitation4 = ExpiredSiaeStaffInvitationFactory()

        pending_invitations = SiaeStaffInvitation.objects.pending()

        assert 3 == pending_invitations.count()
        assert invitation1.pk in pending_invitations.values_list("pk", flat=True)
        assert invitation2.pk in pending_invitations.values_list("pk", flat=True)
        assert invitation3.pk in pending_invitations.values_list("pk", flat=True)

        assert invitation4.pk not in pending_invitations.values_list("pk", flat=True)


class InvitationModelTest(SimpleTestCase):
    def test_acceptance_link(self):
        invitation = SentSiaeStaffInvitationFactory.build()
        assert str(invitation.pk) in invitation.acceptance_link

        # Must be an absolute URL
        assert invitation.acceptance_link.startswith("http")

    def has_expired(self):
        invitation = ExpiredSiaeStaffInvitationFactory.build()
        assert invitation.has_expired

        invitation = SentSiaeStaffInvitationFactory.build()
        assert not invitation.has_expired

    def test_can_be_accepted(self):
        invitation = ExpiredSiaeStaffInvitationFactory.build()
        assert not invitation.can_be_accepted

        invitation = SiaeStaffInvitationFactory.build(sent_at=timezone.now())
        assert not invitation.can_be_accepted

        invitation = SentSiaeStaffInvitationFactory.build(accepted=True)
        assert not invitation.can_be_accepted

        invitation = SentSiaeStaffInvitationFactory.build()
        assert invitation.can_be_accepted

    def test_get_model_from_string(self):
        invitation_type = InvitationAbstract.get_model_from_string("siae_staff")
        assert invitation_type == SiaeStaffInvitation

        with pytest.raises(TypeError):
            InvitationAbstract.get_model_from_string("wrong_type")

        with pytest.raises(TypeError):
            InvitationAbstract.get_model_from_string(12)


class InvitationEmailsTest(SimpleTestCase):
    def test_send_invitation(self):
        invitation = SentSiaeStaffInvitationFactory.build()
        email = invitation.email_invitation

        # Subject
        assert invitation.sender.get_full_name().title() in email.subject

        # Body
        assert capfirst(invitation.first_name) in email.body
        assert capfirst(invitation.last_name) in email.body
        assert invitation.acceptance_link in email.body

        assert str(timezone.localdate(invitation.expiration_date).day) in email.body

        # To
        assert invitation.email in email.to


################################################################
###################### PrescribersWithOrg ######################
################################################################


class TestPrescriberWithOrgInvitation(TestCase):
    def test_add_member_to_organization(self):
        invitation = PrescriberWithOrgSentInvitationFactory(email="hey@you.com")
        PrescriberFactory(email=invitation.email)
        org_members = invitation.organization.members.count()
        invitation.add_invited_user_to_organization()
        org_members_after = invitation.organization.members.count()
        assert org_members + 1 == org_members_after

    def test_add_inactive_member_back_to_organization(self):
        invitation = PrescriberWithOrgSentInvitationFactory(email="hey@you.com")
        PrescriberMembershipFactory(
            organization=invitation.organization, user__email=invitation.email, is_active=False
        )
        org_members = invitation.organization.members.count()
        org_active_members = invitation.organization.active_members.count()
        invitation.add_invited_user_to_organization()
        org_members_after = invitation.organization.members.count()
        org_active_members_after = invitation.organization.active_members.count()
        assert org_members == org_members_after
        assert org_active_members + 1 == org_active_members_after


class TestPrescriberWithOrgInvitationEmails(SimpleTestCase):
    def test_accepted_notif_sender(self):
        invitation = PrescriberWithOrgSentInvitationFactory.build()
        email = invitation.email_accepted_notif_sender

        # Subject
        assert capfirst(invitation.first_name) in email.subject
        assert capfirst(invitation.last_name) in email.subject

        # Body
        assert capfirst(invitation.first_name) in email.body
        assert capfirst(invitation.last_name) in email.body
        assert invitation.email in email.body
        assert invitation.organization.display_name in email.body

        # To
        assert invitation.sender.email in email.to

    def test_email_invitation(self):
        invitation = PrescriberWithOrgSentInvitationFactory.build()
        email = invitation.email_invitation

        # Subject
        assert invitation.organization.display_name in email.subject

        # Body
        assert capfirst(invitation.first_name) in email.body
        assert capfirst(invitation.last_name) in email.body
        assert invitation.acceptance_link in email.body
        assert invitation.organization.display_name in email.body

        # To
        assert invitation.email in email.to


class TestSiaeInvitation(TestCase):
    def test_add_member_to_siae(self):
        invitation = SentSiaeStaffInvitationFactory(email="hey@you.com")
        SiaeStaffFactory(email=invitation.email)
        siae_members = invitation.siae.members.count()
        invitation.add_invited_user_to_siae()
        siae_members_after = invitation.siae.members.count()
        assert siae_members + 1 == siae_members_after

    def test_add_inactive_member_back_to_siae(self):
        invitation = SentSiaeStaffInvitationFactory(email="hey@you.com")
        SiaeMembershipFactory(siae=invitation.siae, user__email=invitation.email, is_active=False)
        siae_members = invitation.siae.members.count()
        siae_active_members = invitation.siae.active_members.count()
        invitation.add_invited_user_to_siae()
        siae_members_after = invitation.siae.members.count()
        siae_active_members_after = invitation.siae.active_members.count()
        assert siae_members == siae_members_after
        assert siae_active_members + 1 == siae_active_members_after


class TestSiaeInvitationEmails(SimpleTestCase):
    def test_accepted_notif_sender(self):
        invitation = SentSiaeStaffInvitationFactory.build()
        email = invitation.email_accepted_notif_sender

        # Subject
        assert capfirst(invitation.first_name) in email.subject
        assert capfirst(invitation.last_name) in email.subject

        # Body
        assert capfirst(invitation.first_name) in email.body
        assert capfirst(invitation.last_name) in email.body
        assert invitation.email in email.body
        assert invitation.siae.display_name in email.body

        # To
        assert invitation.sender.email in email.to

    def test_email_invitation(self):
        invitation = SentSiaeStaffInvitationFactory.build()
        email = invitation.email_invitation

        # Subject
        assert invitation.siae.display_name in email.subject

        # Body
        assert capfirst(invitation.first_name) in email.body
        assert capfirst(invitation.last_name) in email.body
        assert invitation.acceptance_link in email.body
        assert invitation.siae.display_name in email.body

        # To
        assert invitation.email in email.to
