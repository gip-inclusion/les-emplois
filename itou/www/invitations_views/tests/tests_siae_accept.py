from allauth.account.models import EmailAddress
from django.contrib.messages import get_messages
from django.core import mail
from django.shortcuts import reverse
from django.test import TestCase

from itou.invitations.factories import (
    ExpiredSiaeStaffInvitationFactory,
    SentSiaeStaffInvitationFactory,
    SiaeSentInvitationFactory,
)
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeWith2MembershipsFactory
from itou.users.factories import DEFAULT_PASSWORD, UserFactory
from itou.users.models import User
from itou.utils.perms.siae import get_current_siae_or_404


class TestAcceptInvitation(TestCase):
    def test_accept_invitation_signup(self):
        invitation = SentSiaeStaffInvitationFactory()

        response = self.client.get(invitation.acceptance_link, follow=True)

        form_data = {"first_name": invitation.first_name, "last_name": invitation.last_name}

        # Assert data is already present and not editable
        form = response.context.get("form")
        for key, data in form_data.items():
            self.assertEqual(form.fields[key].initial, data)

        total_users_before = User.objects.count()

        # Fill in the password and send
        response = self.client.post(
            invitation.acceptance_link,
            data={**form_data, "password1": "Erls92#32", "password2": "Erls92#32"},
            follow=True,
        )
        self.assertRedirects(response, reverse("dashboard:index"))
        total_users_after = User.objects.count()

        self.assertEqual((total_users_before + 1), total_users_after)

        user = User.objects.get(email=invitation.email)
        self.assertTrue(user.emailaddress_set.first().verified)

    def test_accept_invitation_logged_in_user(self):
        # A logged in user should log out before accepting an invitation.
        logged_in_user = UserFactory()
        self.client.login(email=logged_in_user.email, password=DEFAULT_PASSWORD)
        # Invitation for another user
        invitation = SentSiaeStaffInvitationFactory(email="loutre@example.com")
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertRedirects(response, reverse("account_logout"))

    def test_accept_invitation_signup_changed_email(self):
        invitation = SentSiaeStaffInvitationFactory()

        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertTrue(response.status_code, 200)

        # Email is based on the invitation object.
        # The user changes it because c'est un petit malin.
        form_data = {
            "first_name": invitation.first_name,
            "last_name": invitation.last_name,
            "email": "hey@you.com",
            "password1": "Erls92#32",
            "password2": "Erls92#32",
        }

        # Fill in the password and send
        response = self.client.post(invitation.acceptance_link, data={**form_data}, follow=True)

        user = User.objects.get(email=invitation.email)
        self.assertEqual(invitation.email, user.email)

    def test_accept_invitation_signup_weak_password(self):
        invitation = SentSiaeStaffInvitationFactory()
        form_data = {"first_name": invitation.first_name, "last_name": invitation.last_name, "email": invitation.email}

        # Fill in the password and send
        response = self.client.post(
            invitation.acceptance_link,
            data={**form_data, "password1": "password", "password2": "password"},
            follow=True,
        )
        self.assertFalse(response.context["form"].is_valid())
        self.assertTrue(response.context["form"].errors.get("password1"))
        self.assertTrue(response.wsgi_request.path, invitation.acceptance_link)

    def test_expired_invitation(self):
        invitation = ExpiredSiaeStaffInvitationFactory()

        # User wants to join our website but it's too late!
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "expirée")

    def test_non_existent_invitation(self):
        invitation = SentSiaeStaffInvitationFactory.build(
            first_name="Léonie", last_name="Bathiat", email="leonie@bathiat.com"
        )
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertEqual(response.status_code, 404)

    def test_accepted_invitation(self):
        invitation = SentSiaeStaffInvitationFactory(accepted=True)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "acceptée")


class TestAcceptSiaeInvitation(TestCase):
    def setUp(self):
        self.siae = SiaeWith2MembershipsFactory()
        self.sender = self.siae.members.first()
        self.invitation = SiaeSentInvitationFactory(sender=self.sender, siae=self.siae)
        self.user = None
        self.response = None

    def assert_accepted_invitation(self):
        self.assertEqual(self.response.status_code, 200)
        self.user.refresh_from_db()
        self.invitation.refresh_from_db()
        self.assertTrue(self.user.is_siae_staff)
        self.assertTrue(self.invitation.accepted)
        self.assertTrue(self.invitation.accepted_at)
        self.assertEqual(self.siae.members.count(), 3)

        self.assertEqual(reverse("dashboard:index"), self.response.wsgi_request.path)
        # Make sure there's a welcome message.
        messages = list(get_messages(self.response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].level_tag, "success")

        # A confirmation e-mail is sent to the invitation sender.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].to), 1)
        self.assertEqual(self.invitation.sender.email, mail.outbox[0].to[0])

    def test_accept_siae_invitation(self):
        response = self.client.get(self.invitation.acceptance_link, follow=True)
        self.assertIn(response.wsgi_request.path, self.invitation.acceptance_link)

        form_data = {
            "first_name": self.invitation.first_name,
            "last_name": self.invitation.last_name,
            "password1": "Erls92#32",
            "password2": "Erls92#32",
        }

        self.response = self.client.post(self.invitation.acceptance_link, data=form_data, follow=True)

        self.user = User.objects.get(email=self.invitation.email)
        self.assert_accepted_invitation()

    def test_accept_existing_user_is_employer(self):
        self.user = SiaeWith2MembershipsFactory().members.first()
        self.invitation = SentSiaeStaffInvitationFactory(
            sender=self.sender,
            siae=self.siae,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
            email=self.user.email,
        )
        self.client.login(email=self.user.email, password=DEFAULT_PASSWORD)
        self.response = self.client.get(self.invitation.acceptance_link, follow=True)

        current_siae = get_current_siae_or_404(self.response.wsgi_request)
        self.assertEqual(self.invitation.siae.pk, current_siae.pk)
        self.assert_accepted_invitation()

    def test_accept_existing_user_with_existing_inactive_siae(self):
        """
        An inactive siae user (i.e. attached to a single inactive siae)
        can only be ressucitated by being invited to a new siae.
        We test here that this is indeed possible.
        """
        self.user = SiaeWith2MembershipsFactory(convention__is_active=False).members.first()
        self.invitation = SentSiaeStaffInvitationFactory(
            sender=self.sender,
            siae=self.siae,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
            email=self.user.email,
        )
        self.client.login(email=self.user.email, password=DEFAULT_PASSWORD)
        self.response = self.client.get(self.invitation.acceptance_link, follow=True)

        current_siae = get_current_siae_or_404(self.response.wsgi_request)
        self.assertEqual(self.invitation.siae.pk, current_siae.pk)
        self.assert_accepted_invitation()

    def test_accept_existing_user_not_logged_in(self):
        self.user = SiaeWith2MembershipsFactory().members.first()
        # The user verified its email
        EmailAddress(user_id=self.user.pk, email=self.user.email, verified=True, primary=True).save()
        self.invitation = SentSiaeStaffInvitationFactory(
            sender=self.sender,
            siae=self.siae,
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
        self.assert_accepted_invitation()

    def test_accept_existing_user_is_not_employer(self):
        self.user = PrescriberOrganizationWithMembershipFactory().members.first()
        self.invitation = SentSiaeStaffInvitationFactory(
            sender=self.sender,
            siae=self.siae,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
            email=self.user.email,
        )

        self.client.login(email=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.invitation.acceptance_link, follow=True)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.invitation.accepted)

    def test_accept_connected_user_is_not_the_invited_user(self):
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.invitation.acceptance_link, follow=True)

        self.assertEqual(reverse("account_logout"), response.wsgi_request.path)
        self.assertFalse(self.invitation.accepted)
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
