import pytest
from django.test import SimpleTestCase
from django.utils import timezone

from itou.invitations.models import EmployerInvitation, InvitationAbstract
from itou.users.enums import KIND_EMPLOYER
from tests.companies.factories import CompanyMembershipFactory
from tests.invitations.factories import (
    EmployerInvitationFactory,
    ExpiredEmployerInvitationFactory,
    PrescriberWithOrgSentInvitationFactory,
    SentEmployerInvitationFactory,
)
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, PrescriberFactory
from tests.utils.test import TestCase


class EmployerInvitationQuerySetTest(TestCase):
    def test_pending(self):
        # Create some non-expired invitations.
        invitation1 = SentEmployerInvitationFactory()
        invitation2 = SentEmployerInvitationFactory()
        invitation3 = SentEmployerInvitationFactory()

        # Add one expired invitation.
        invitation4 = ExpiredEmployerInvitationFactory()

        pending_invitations = EmployerInvitation.objects.pending()

        assert 3 == pending_invitations.count()
        assert invitation1.pk in pending_invitations.values_list("pk", flat=True)
        assert invitation2.pk in pending_invitations.values_list("pk", flat=True)
        assert invitation3.pk in pending_invitations.values_list("pk", flat=True)

        assert invitation4.pk not in pending_invitations.values_list("pk", flat=True)


class InvitationModelTest(SimpleTestCase):
    def test_acceptance_link(self):
        invitation = SentEmployerInvitationFactory.build()
        assert str(invitation.pk) in invitation.acceptance_link

        # Must be an absolute URL
        assert invitation.acceptance_link.startswith("http")

    def has_expired(self):
        invitation = ExpiredEmployerInvitationFactory.build()
        assert invitation.has_expired

        invitation = SentEmployerInvitationFactory.build()
        assert not invitation.has_expired

    def test_can_be_accepted(self):
        invitation = ExpiredEmployerInvitationFactory.build()
        assert not invitation.can_be_accepted

        invitation = EmployerInvitationFactory.build(sent_at=timezone.now())
        assert not invitation.can_be_accepted

        invitation = SentEmployerInvitationFactory.build(accepted=True)
        assert not invitation.can_be_accepted

        invitation = SentEmployerInvitationFactory.build()
        assert invitation.can_be_accepted

    def test_get_model_from_string(self):
        invitation_type = InvitationAbstract.get_model_from_string(KIND_EMPLOYER)
        assert invitation_type == EmployerInvitation

        with pytest.raises(TypeError):
            InvitationAbstract.get_model_from_string("wrong_type")

        with pytest.raises(TypeError):
            InvitationAbstract.get_model_from_string(12)


class InvitationEmailsTest(SimpleTestCase):
    def test_send_invitation(self):
        invitation = SentEmployerInvitationFactory.build()
        email = invitation.email_invitation

        # Subject
        assert invitation.sender.get_full_name() in email.subject

        # Body
        assert invitation.first_name.title() in email.body
        assert invitation.last_name.upper() in email.body
        assert invitation.acceptance_link in email.body

        assert str(timezone.localdate(invitation.expiration_date).day) in email.body

        # To
        assert invitation.email in email.to


################################################################
###################### PrescribersWithOrg ######################
################################################################


class TestPrescriberWithOrgInvitation(TestCase):
    def test_add_or_activate_member_to_organization(self):
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
        email = invitation.notifications_accepted_notif_sender.build()

        # Subject
        assert invitation.first_name.title() in email.subject
        assert invitation.last_name.upper() in email.subject

        # Body
        assert invitation.first_name.title() in email.body
        assert invitation.last_name.upper() in email.body
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
        assert invitation.first_name.title() in email.body
        assert invitation.last_name.upper() in email.body
        assert invitation.acceptance_link in email.body
        assert invitation.organization.display_name in email.body

        # To
        assert invitation.email in email.to


class TestCompanyInvitation(TestCase):
    def test_add_or_activate_member_to_company(self):
        invitation = SentEmployerInvitationFactory(email="hey@you.com")
        EmployerFactory(email=invitation.email)
        employers = invitation.company.members.count()
        invitation.add_invited_user_to_company()
        employers_after = invitation.company.members.count()
        assert employers + 1 == employers_after

    def test_add_inactive_member_back_to_company(self):
        invitation = SentEmployerInvitationFactory(email="hey@you.com")
        CompanyMembershipFactory(company=invitation.company, user__email=invitation.email, is_active=False)
        employers = invitation.company.members.count()
        company_active_members = invitation.company.active_members.count()
        invitation.add_invited_user_to_company()
        employers_after = invitation.company.members.count()
        company_active_members_after = invitation.company.active_members.count()
        assert employers == employers_after
        assert company_active_members + 1 == company_active_members_after


class TestCompanyInvitationEmails(SimpleTestCase):
    def test_accepted_notif_sender(self):
        invitation = SentEmployerInvitationFactory.build()
        email = invitation.notifications_accepted_notif_sender.build()

        # Subject
        assert invitation.first_name.title() in email.subject
        assert invitation.last_name.upper() in email.subject

        # Body
        assert invitation.first_name.title() in email.body
        assert invitation.last_name.upper() in email.body
        assert invitation.email in email.body
        assert invitation.company.display_name in email.body

        # To
        assert invitation.sender.email in email.to

    def test_email_invitation(self):
        invitation = SentEmployerInvitationFactory.build()
        email = invitation.email_invitation

        # Subject
        assert invitation.company.display_name in email.subject

        # Body
        assert invitation.first_name.title() in email.body
        assert invitation.last_name.upper() in email.body
        assert invitation.acceptance_link in email.body
        assert invitation.company.display_name in email.body

        # To
        assert invitation.email in email.to
