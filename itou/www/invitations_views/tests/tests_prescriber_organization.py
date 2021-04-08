from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.messages import get_messages
from django.core import mail
from django.shortcuts import reverse
from django.test import TestCase

from itou.invitations.factories import PrescriberWithOrgSentInvitationFactory
from itou.invitations.models import PrescriberWithOrgInvitation
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory, PrescriberPoleEmploiFactory
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.factories import SiaeWithMembershipFactory
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, PrescriberFactory, UserFactory
from itou.users.models import User
from itou.utils.perms.prescriber import get_current_org_or_404


POST_DATA = {
    "form-TOTAL_FORMS": "1",
    "form-INITIAL_FORMS": "0",
    "form-MIN_NUM_FORMS": "",
    "form-MAX_NUM_FORMS": "",
}

INVITATION_URL = reverse("invitations_views:invite_prescriber_with_org")


class TestSendPrescriberWithOrgInvitation(TestCase):
    def setUp(self):
        self.organization = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganization.Kind.CAP_EMPLOI)
        self.sender = self.organization.members.first()
        self.guest_data = {"first_name": "Léonie", "last_name": "Bathiat", "email": "leonie@example.com"}
        self.post_data = POST_DATA | {
            "form-0-first_name": self.guest_data["first_name"],
            "form-0-last_name": self.guest_data["last_name"],
            "form-0-email": self.guest_data["email"],
        }
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)

    def assert_created_invitation(self):
        invitation = PrescriberWithOrgInvitation.objects.get(organization=self.organization)
        self.assertEqual(invitation.first_name, self.post_data["form-0-first_name"])
        self.assertEqual(invitation.last_name, self.post_data["form-0-last_name"])
        self.assertEqual(invitation.email, self.post_data["form-0-email"])

    def test_invite_not_existing_user(self):
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertRedirects(response, INVITATION_URL)
        self.assert_created_invitation()

    def test_invite_existing_user_is_prescriber_without_org(self):
        guest = PrescriberFactory()
        self.post_data["form-0-first_name"] = guest.first_name
        self.post_data["form-0-last_name"] = guest.last_name
        self.post_data["form-0-email"] = guest.email
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertRedirects(response, INVITATION_URL)
        self.assert_created_invitation()

    def test_invite_former_member(self):
        """
        Admins can "deactivate" members of the organization (making the membership inactive).
        A deactivated member must be able to receive new invitations.
        """
        # Invite user (part 1)
        guest = PrescriberFactory()
        self.post_data["form-0-first_name"] = guest.first_name
        self.post_data["form-0-last_name"] = guest.last_name
        self.post_data["form-0-email"] = guest.email
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertRedirects(response, INVITATION_URL)
        self.assert_created_invitation()

        # Deactivate user
        self.organization.members.add(guest)
        guest.save()
        membership = guest.prescribermembership_set.first()
        membership.deactivate_membership_by_user(self.organization.members.first())
        membership.save()
        self.assertFalse(guest in self.organization.active_members)
        # Invite user (the revenge)
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertRedirects(response, INVITATION_URL)
        self.assert_created_invitation()


class TestSendPrescriberWithOrgInvitationExceptions(TestCase):
    def setUp(self):
        self.organization = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganization.Kind.CAP_EMPLOI)
        self.sender = self.organization.members.first()
        self.post_data = POST_DATA

    def test_invite_existing_user_is_employer(self):
        guest = SiaeWithMembershipFactory().members.first()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data.update(
            {"form-0-first_name": guest.first_name, "form-0-last_name": guest.last_name, "form-0-email": guest.email}
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        self.assertEqual(response.status_code, 200)

        # Make sure form is not valid
        self.assertFalse(response.context["formset"].is_valid())
        self.assertTrue(response.context["formset"].errors[0].get("email"))
        self.assertFalse(PrescriberWithOrgInvitation.objects.exists())

    def test_invite_existing_user_is_job_seeker(self):
        guest = JobSeekerFactory()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data.update(
            {"form-0-first_name": guest.first_name, "form-0-last_name": guest.last_name, "form-0-email": guest.email}
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        self.assertEqual(response.status_code, 200)
        # Make sure form is not valid
        self.assertFalse(response.context["formset"].is_valid())
        self.assertTrue(response.context["formset"].errors[0].get("email"))
        self.assertFalse(PrescriberWithOrgInvitation.objects.exists())

    def test_already_a_member(self):
        # The invited user is already a member
        self.organization.members.add(PrescriberFactory())
        guest = self.organization.members.exclude(email=self.sender.email).first()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data.update(
            {"form-0-first_name": guest.first_name, "form-0-last_name": guest.last_name, "form-0-email": guest.email}
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        self.assertEqual(response.status_code, 200)
        # Make sure form is not valid
        self.assertFalse(response.context["formset"].is_valid())
        self.assertTrue(response.context["formset"].errors[0].get("email"))
        self.assertFalse(PrescriberWithOrgInvitation.objects.exists())


class TestPEOrganizationInvitation(TestCase):
    def setUp(self):
        self.organization = PrescriberPoleEmploiFactory()
        self.organization.members.add(PrescriberFactory())
        self.sender = self.organization.members.first()

    def test_pe_organization_invitation_successful(self):
        guest = UserFactory.build(email=f"sabine.lagrange{settings.POLE_EMPLOI_EMAIL_SUFFIX}")
        post_data = POST_DATA | {
            "form-0-first_name": guest.first_name,
            "form-0-last_name": guest.last_name,
            "form-0-email": guest.email,
        }
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        response = self.client.post(INVITATION_URL, data=post_data, follow=True)
        self.assertRedirects(response, INVITATION_URL)

    def test_pe_organization_invitation_unsuccessful(self):
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        post_data = POST_DATA | {
            "form-0-first_name": "René",
            "form-0-last_name": "Boucher",
            "form-0-email": "rene@example.com",
        }

        response = self.client.post(INVITATION_URL, data=post_data)
        # Make sure form is invalid
        self.assertFalse(response.context["formset"].is_valid())
        self.assertTrue(response.context["formset"].errors[0].get("email"))


class TestAcceptPrescriberWithOrgInvitation(TestCase):
    def setUp(self):
        self.organization = PrescriberOrganizationWithMembershipFactory()
        # Create a second member to make sure emails are also
        # sent to regular members
        self.organization.members.add(PrescriberFactory())
        self.organization.save()
        self.sender = self.organization.members.first()
        self.invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.organization)
        self.user = None
        self.response = None

    def tearDown(self):
        self.assertEqual(self.response.status_code, 200)
        self.user.refresh_from_db()
        self.invitation.refresh_from_db()
        self.assertTrue(self.user.is_prescriber)
        self.assertTrue(self.invitation.accepted)
        self.assertTrue(self.invitation.accepted_at)
        self.assertEqual(self.organization.members.count(), 3)

        self.assertEqual(reverse("dashboard:index"), self.response.wsgi_request.path)
        # Make sure there's a welcome message.
        messages = list(get_messages(self.response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].level_tag, "success")

        # A confirmation e-mail is sent to the invitation sender.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].to), 1)
        self.assertEqual(self.invitation.sender.email, mail.outbox[0].to[0])

        # Assert the user sees his new organization dashboard.
        current_org = get_current_org_or_404(self.response.wsgi_request)
        # A user can be member of one or more organizations
        self.assertTrue(current_org in self.user.prescriberorganization_set.all())

    def test_accept_prescriber_org_invitation(self):
        post_data = {
            "first_name": self.invitation.first_name,
            "last_name": self.invitation.last_name,
            "password1": "Erls92#32",
            "password2": "Erls92#32",
        }

        self.response = self.client.post(self.invitation.acceptance_link, data=post_data, follow=True)
        self.user = User.objects.get(email=self.invitation.email)

    def test_accept_existing_user_is_prescriber_without_org(self):
        self.user = PrescriberFactory()
        self.invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
            email=self.user.email,
        )
        self.client.login(email=self.user.email, password=DEFAULT_PASSWORD)
        self.response = self.client.get(self.invitation.acceptance_link, follow=True)

    def test_accept_existing_user_belongs_to_another_organization(self):
        self.user = PrescriberOrganizationWithMembershipFactory().members.first()
        self.invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
            email=self.user.email,
        )
        self.client.login(email=self.user.email, password=DEFAULT_PASSWORD)
        self.response = self.client.get(self.invitation.acceptance_link, follow=True)

    def test_accept_existing_user_not_logged_in(self):
        self.user = PrescriberFactory()
        # The user verified its email
        EmailAddress(user_id=self.user.pk, email=self.user.email, verified=True, primary=True).save()
        self.invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
            email=self.user.email,
        )
        response = self.client.get(self.invitation.acceptance_link, follow=True)

        self.assertIn(reverse("account_login"), response.wsgi_request.get_full_path())
        self.assertFalse(self.invitation.accepted)

        self.response = self.client.post(
            response.wsgi_request.get_full_path(),
            data={"login": self.user.email, "password": DEFAULT_PASSWORD},
            follow=True,
        )
        self.assertTrue(self.response.wsgi_request.user.is_authenticated)


class TestAcceptPrescriberWithOrgInvitationExceptions(TestCase):
    def setUp(self):
        self.organization = PrescriberOrganizationWithMembershipFactory()
        self.sender = self.organization.members.first()
        self.invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.organization)
        self.user = None

    def test_existing_user_is_not_prescriber(self):
        self.user = SiaeWithMembershipFactory().members.first()
        self.invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
            email=self.user.email,
        )

        self.client.login(email=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.invitation.acceptance_link, follow=True)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.invitation.accepted)

    def test_connected_user_is_not_the_invited_user(self):
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.invitation.acceptance_link, follow=True)

        self.assertEqual(reverse("account_logout"), response.wsgi_request.path)
        self.assertFalse(self.invitation.accepted)
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
