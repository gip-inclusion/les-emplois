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

    def assert_invalid_user(self, response, reason):
        self.assertFalse(response.context["formset"].is_valid())
        self.assertEqual(response.context["formset"].errors[0]["email"][0], reason)
        self.assertFalse(PrescriberWithOrgInvitation.objects.exists())

    def test_invite_existing_user_is_employer(self):
        guest = SiaeWithMembershipFactory().members.first()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data.update(
            {"form-0-first_name": guest.first_name, "form-0-last_name": guest.last_name, "form-0-email": guest.email}
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        self.assertEqual(response.status_code, 200)
        self.assert_invalid_user(response, "Cet utilisateur n'est pas un prescripteur.")

    def test_invite_existing_user_is_job_seeker(self):
        guest = JobSeekerFactory()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data.update(
            {"form-0-first_name": guest.first_name, "form-0-last_name": guest.last_name, "form-0-email": guest.email}
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        self.assertEqual(response.status_code, 200)
        self.assert_invalid_user(response, "Cet utilisateur n'est pas un prescripteur.")

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
        self.assert_invalid_user(response, "Cette personne fait déjà partie de votre organisation.")


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
        self.assertEqual(
            response.context["formset"].errors[0]["email"][0], "L'adresse e-mail doit être une adresse Pôle emploi"
        )


DASHBOARD_URL = reverse("dashboard:index")


class TestAcceptPrescriberWithOrgInvitation(TestCase):
    def setUp(self):
        self.organization = PrescriberOrganizationWithMembershipFactory()
        # Create a second member to make sure emails are also
        # sent to regular members
        self.organization.members.add(PrescriberFactory())
        self.organization.save()
        self.sender = self.organization.members.first()

    def assert_invitation_is_accepted(self, response, user, invitation):
        self.assertRedirects(response, DASHBOARD_URL)

        user.refresh_from_db()
        invitation.refresh_from_db()
        self.assertTrue(user.is_prescriber)

        self.assertTrue(invitation.accepted)
        self.assertTrue(invitation.accepted_at)
        self.assertEqual(self.organization.members.count(), 3)

        # Make sure there's a welcome message.
        messages = list(response.context["messages"])
        self.assertEqual(messages[0].level_tag, "success")
        self.assertEqual(
            str(messages[0]), f"Vous êtes désormais membre de l'organisation {self.organization.display_name}."
        )

        # A confirmation e-mail is sent to the invitation sender.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].to), 1)
        self.assertEqual(invitation.sender.email, mail.outbox[0].to[0])

        # Assert the user sees his new organization dashboard.
        current_org = get_current_org_or_404(response.wsgi_request)
        # A user can be member of one or more organizations
        self.assertTrue(current_org in user.prescriberorganization_set.all())

    def test_accept_prescriber_org_invitation(self):
        invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.organization)
        post_data = {
            "first_name": invitation.first_name,
            "last_name": invitation.last_name,
            "password1": "Erls92#32",
            "password2": "Erls92#32",
        }

        response = self.client.post(invitation.acceptance_link, data=post_data, follow=True)
        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation)

    def test_accept_existing_user_is_prescriber_without_org(self):
        user = PrescriberFactory()
        invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assert_invitation_is_accepted(response, user, invitation)

    def test_accept_existing_user_belongs_to_another_organization(self):
        user = PrescriberOrganizationWithMembershipFactory().members.first()
        invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assert_invitation_is_accepted(response, user, invitation)

    def test_accept_existing_user_not_logged_in(self):
        invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.organization)
        user = PrescriberFactory()
        # The user verified its email
        EmailAddress(user_id=user.pk, email=user.email, verified=True, primary=True).save()
        invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertIn(reverse("account_login"), response.wsgi_request.get_full_path())
        self.assertFalse(invitation.accepted)

        response = self.client.post(
            response.wsgi_request.get_full_path(),
            data={"login": user.email, "password": DEFAULT_PASSWORD},
            follow=True,
        )
        self.assertTrue(response.context["user"].is_authenticated)
        self.assert_invitation_is_accepted(response, user, invitation)


class TestAcceptPrescriberWithOrgInvitationExceptions(TestCase):
    def setUp(self):
        self.organization = PrescriberOrganizationWithMembershipFactory()
        self.sender = self.organization.members.first()

    def test_existing_user_is_not_prescriber(self):
        user = SiaeWithMembershipFactory().members.first()
        invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )

        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(invitation.accepted)

    def test_connected_user_is_not_the_invited_user(self):
        invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.organization)
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertRedirects(response, reverse("account_logout"))
        self.assertFalse(invitation.accepted)
        messages = list(response.context["messages"])
        self.assertEqual(len(messages), 1)
