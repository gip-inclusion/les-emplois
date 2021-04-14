from django.core import mail
from django.shortcuts import reverse
from django.test import TestCase
from django.utils import timezone
from django.utils.html import escape

from itou.invitations.factories import ExpiredSiaeStaffInvitationFactory
from itou.invitations.models import SiaeStaffInvitation
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeMembershipFactory, SiaeWithMembershipFactory
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, UserFactory
from itou.www.invitations_views.forms import SiaeStaffInvitationForm


INVITATION_URL = reverse("invitations_views:invite_siae_staff")


class TestSendSingleSiaeInvitation(TestCase):
    def setUp(self):
        self.siae = SiaeWithMembershipFactory()
        # The sender is a member of the SIAE
        self.sender = self.siae.members.first()
        self.guest_data = {"first_name": "Léonie", "last_name": "Bathiat", "email": "leonie@example.com"}
        self.post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": self.guest_data["first_name"],
            "form-0-last_name": self.guest_data["last_name"],
            "form-0-email": self.guest_data["email"],
        }

    def test_send_one_invitation(self):
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        response = self.client.get(INVITATION_URL)

        # Assert form is present
        form = SiaeStaffInvitationForm(sender=self.sender, siae=self.siae)
        self.assertContains(response, form["first_name"].label)
        self.assertContains(response, form["last_name"].label)
        self.assertContains(response, form["email"].label)

        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertContains(response, "Votre invitation a été envoyée par e-mail.")

        invitations = SiaeStaffInvitation.objects.all()
        self.assertEqual(len(invitations), 1)

        invitation = invitations[0]
        self.assertEqual(invitation.sender.pk, self.sender.pk)
        self.assertTrue(invitation.sent)

        # Make sure an email has been sent to the invited person
        outbox_emails = [receiver for message in mail.outbox for receiver in message.to]
        self.assertIn(self.post_data["form-0-email"], outbox_emails)

    def test_send_invitation_user_already_exists(self):
        guest = UserFactory(
            first_name=self.guest_data["first_name"],
            last_name=self.guest_data["last_name"],
            email=self.guest_data["email"],
            is_siae_staff=True,
        )
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # The guest will be able to join the structure
        invitations = SiaeStaffInvitation.objects.all()
        self.assertEqual(len(invitations), 1)

        invitation = invitations[0]

        # At least one complete test of the invitation fields in our test suite
        self.assertFalse(invitation.accepted)
        self.assertTrue(invitation.sent_at < timezone.now())
        self.assertEqual(invitation.first_name, guest.first_name)
        self.assertEqual(invitation.last_name, guest.last_name)
        self.assertEqual(invitation.email, guest.email)
        self.assertEqual(invitation.sender, self.sender)
        self.assertEqual(invitation.siae, self.siae)
        self.assertEqual(invitation.SIGNIN_ACCOUNT_TYPE, "siae")

    def test_send_invitation_to_not_employer(self):
        UserFactory(
            first_name=self.guest_data["first_name"],
            last_name=self.guest_data["last_name"],
            email=self.guest_data["email"],
        )
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        response = self.client.post(INVITATION_URL, data=self.post_data)

        for error_dict in response.context["formset"].errors:
            for key, _errors in error_dict.items():
                self.assertEqual(key, "email")
                self.assertEqual(error_dict["email"][0], "Cet utilisateur n'est pas un employeur.")

    def test_extend_expired_invitation(self):
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        ExpiredSiaeStaffInvitationFactory(
            sender=self.sender,
            first_name=self.guest_data["first_name"],
            last_name=self.guest_data["last_name"],
            email=self.guest_data["email"],
            siae=self.siae,
        )
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertContains(response, "Votre invitation a été envoyée par e-mail.")

        # Make sure an email has been sent to the invited person
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.guest_data["email"], mail.outbox[0].to)

        # but there is still only one invitation in DB
        self.assertEqual(SiaeStaffInvitation.objects.count(), 1)

    def test_two_employers_invite_the_same_guest(self):
        # SIAE 1 invites guest.
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertEqual(SiaeStaffInvitation.objects.count(), 1)

        # SIAE 2 invites guest as well.
        siae_2 = SiaeWithMembershipFactory()
        sender_2 = siae_2.members.first()
        self.client.login(email=sender_2.email, password=DEFAULT_PASSWORD)
        self.client.post(INVITATION_URL, data=self.post_data)
        self.assertEqual(SiaeStaffInvitation.objects.count(), 2)
        invitation = SiaeStaffInvitation.objects.get(siae=siae_2)
        self.assertEqual(invitation.first_name, self.guest_data["first_name"])
        self.assertEqual(invitation.last_name, self.guest_data["last_name"])
        self.assertEqual(invitation.email, self.guest_data["email"])


class TestSendMultipleSiaeInvitation(TestCase):
    def setUp(self):
        self.siae = SiaeWithMembershipFactory()
        # The sender is a member of the SIAE
        self.sender = self.siae.members.first()
        # Define instances not created in DB
        self.invited_user = UserFactory.build()
        self.second_invited_user = UserFactory.build()
        self.post_data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": self.invited_user.first_name,
            "form-0-last_name": self.invited_user.last_name,
            "form-0-email": self.invited_user.email,
            "form-1-first_name": self.second_invited_user.first_name,
            "form-1-last_name": self.second_invited_user.last_name,
            "form-1-email": self.second_invited_user.email,
        }

    def test_send_multiple_invitations(self):
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        response = self.client.get(INVITATION_URL)

        self.assertTrue(response.context["formset"])
        self.client.post(INVITATION_URL, data=self.post_data)
        invitations = SiaeStaffInvitation.objects.count()
        self.assertEqual(invitations, 2)

    def test_send_multiple_invitations_duplicated_email(self):
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        response = self.client.get(INVITATION_URL)

        self.assertTrue(response.context["formset"])
        # The formset should ensure there are no duplicates in emails
        self.post_data.update(
            {
                "form-TOTAL_FORMS": "3",
                "form-2-first_name": self.invited_user.first_name,
                "form-2-last_name": self.invited_user.last_name,
                "form-2-email": self.invited_user.email,
            }
        )
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertContains(
            response,
            escape("Les invitations doivent avoir des adresses e-mail différentes."),
        )
        invitations = SiaeStaffInvitation.objects.count()
        self.assertEqual(invitations, 0)


class TestSendInvitationToSpecialGuest(TestCase):
    def setUp(self):
        self.sender_siae = SiaeWithMembershipFactory()
        self.sender = self.sender_siae.members.first()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
        }

    def test_invite_existing_user_with_existing_inactive_siae(self):
        """
        An inactive SIAIE user (i.e. attached to a single inactive siae)
        can only be ressucitated by being invited to a new SIAE.
        We test here that this is indeed possible.
        """
        guest = SiaeWithMembershipFactory(convention__is_active=False).members.first()
        self.post_data.update(
            {
                "form-0-first_name": guest.first_name,
                "form-0-last_name": guest.last_name,
                "form-0-email": guest.email,
            }
        )
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SiaeStaffInvitation.objects.count(), 1)

    def test_invite_former_siae_member(self):
        """
        Admins can "deactivate" members of the organization (making the membership inactive).
        A deactivated member must be able to receive new invitations.
        """
        guest = SiaeWithMembershipFactory().members.first()

        # Deactivate user
        membership = guest.siaemembership_set.first()
        membership.deactivate_membership_by_user(self.sender_siae.members.first())
        membership.save()

        self.post_data.update(
            {
                "form-0-first_name": guest.first_name,
                "form-0-last_name": guest.last_name,
                "form-0-email": guest.email,
            }
        )
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SiaeStaffInvitation.objects.count(), 1)

    def test_invite_existing_user_is_prescriber(self):
        guest = PrescriberOrganizationWithMembershipFactory().members.first()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data.update(
            {
                "form-0-first_name": guest.first_name,
                "form-0-last_name": guest.last_name,
                "form-0-email": guest.email,
            }
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        # The form is invalid
        self.assertFalse(response.context["formset"].is_valid())
        self.assertIn("email", response.context["formset"].errors[0])
        self.assertEqual(response.context["formset"].errors[0]["email"][0], "Cet utilisateur n'est pas un employeur.")
        self.assertEqual(SiaeStaffInvitation.objects.count(), 0)

    def test_invite_existing_user_is_job_seeker(self):
        guest = JobSeekerFactory()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data.update(
            {
                "form-0-first_name": guest.first_name,
                "form-0-last_name": guest.last_name,
                "form-0-email": guest.email,
            }
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        # Make sure form is invalid
        self.assertFalse(response.context["formset"].is_valid())
        self.assertIn("email", response.context["formset"].errors[0])
        self.assertEqual(response.context["formset"].errors[0]["email"][0], "Cet utilisateur n'est pas un employeur.")
        self.assertEqual(SiaeStaffInvitation.objects.count(), 0)

    def test_already_a_member(self):
        # The invited user is already a member
        SiaeMembershipFactory(siae=self.sender_siae, is_siae_admin=False)
        guest = self.sender_siae.members.exclude(email=self.sender.email).first()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data.update(
            {
                "form-0-first_name": guest.first_name,
                "form-0-last_name": guest.last_name,
                "form-0-email": guest.email,
            }
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        # Make sure form is invalid
        self.assertFalse(response.context["formset"].is_valid())
        self.assertIn("email", response.context["formset"].errors[0])
        self.assertEqual(
            response.context["formset"].errors[0]["email"][0], "Cette personne fait déjà partie de votre structure."
        )

        self.assertEqual(SiaeStaffInvitation.objects.count(), 0)
