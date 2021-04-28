import uuid

from django.core import mail
from django.shortcuts import reverse
from django.test import TestCase
from django.utils.html import escape

from itou.invitations.factories import ExpiredSiaeStaffInvitationFactory, SentSiaeStaffInvitationFactory
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipFactory
from itou.users.factories import DEFAULT_PASSWORD, SiaeStaffFactory, UserFactory
from itou.users.models import User
from itou.utils.perms.siae import get_current_siae_or_404


class TestAcceptInvitation(TestCase):
    def assert_accepted_invitation(self, invitation, user):
        user.refresh_from_db()
        invitation.refresh_from_db()
        self.assertTrue(user.is_siae_staff)
        self.assertTrue(invitation.accepted)
        self.assertTrue(invitation.accepted_at)

        # A confirmation e-mail is sent to the invitation sender.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].to), 1)
        self.assertEqual(invitation.sender.email, mail.outbox[0].to[0])

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
        # `username` should be a valid UUID, see `User.generate_unique_username()`.
        self.assertEqual(user.username, uuid.UUID(user.username, version=4).hex)
        self.assert_accepted_invitation(invitation, user)

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
        response = self.client.post(invitation.acceptance_link, data=form_data, follow=True)
        self.assertRedirects(response, reverse("dashboard:index"))

        user = User.objects.get(email=invitation.email)
        self.assertEqual(invitation.email, user.email)

    def test_expired_invitation(self):
        invitation = ExpiredSiaeStaffInvitationFactory()
        self.assertTrue(invitation.has_expired)

        # User wants to join our website but it's too late!
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "expirée")

        user = SiaeStaffFactory(email=invitation.email)
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        join_url = reverse("invitations_views:join_siae", kwargs={"invitation_id": invitation.id})
        response = self.client.get(join_url, follow=True)
        self.assertContains(response, escape("Cette invitation n'est plus valide."))

    def test_inactive_siae(self):
        siae = SiaeFactory(convention__is_active=False)
        invitation = SentSiaeStaffInvitationFactory(siae=siae)
        user = SiaeStaffFactory(email=invitation.email)
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        join_url = reverse("invitations_views:join_siae", kwargs={"invitation_id": invitation.id})
        response = self.client.get(join_url, follow=True)
        self.assertContains(response, escape("Cette structure n'est plus active."))

    def test_non_existent_invitation(self):
        invitation = SentSiaeStaffInvitationFactory.build(
            first_name="Léonie", last_name="Bathiat", email="leonie@bathiat.com"
        )
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertEqual(response.status_code, 404)

    def test_accepted_invitation(self):
        invitation = SentSiaeStaffInvitationFactory(accepted=True)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertContains(response, escape("Invitation acceptée"))

    def test_accept_existing_user_already_member_of_inactive_siae(self):
        """
        An inactive SIAE user (i.e. attached to a single inactive SIAE)
        can only be ressucitated by being invited to a new SIAE.
        We test here that this is indeed possible.
        """
        siae = SiaeWithMembershipFactory()
        sender = siae.members.first()
        user = SiaeWithMembershipFactory(convention__is_active=False).members.first()
        invitation = SentSiaeStaffInvitationFactory(
            sender=sender,
            siae=siae,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertRedirects(response, reverse("dashboard:index"))

        current_siae = get_current_siae_or_404(response.wsgi_request)
        self.assertEqual(siae.pk, current_siae.pk)
        self.assert_accepted_invitation(invitation, user)

    def test_accept_new_user_to_inactive_siae(self):
        siae = SiaeWithMembershipFactory(convention__is_active=False)
        sender = siae.members.first()
        invitation = SentSiaeStaffInvitationFactory(
            sender=sender,
            siae=siae,
        )
        form_data = {
            "first_name": invitation.first_name,
            "last_name": invitation.last_name,
            "email": invitation.email,
            "password1": "Erls92#32",
            "password2": "Erls92#32",
        }
        response = self.client.post(invitation.acceptance_link, data=form_data)
        self.assertContains(response, escape("La structure que vous souhaitez rejoindre n'est plus active."))

    def test_accept_existing_user_is_not_employer(self):
        user = PrescriberOrganizationWithMembershipFactory().members.first()
        invitation = SentSiaeStaffInvitationFactory(
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )

        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(invitation.acceptance_link, follow=True)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(invitation.accepted)

    def test_accept_connected_user_is_not_the_invited_user(self):
        invitation = SentSiaeStaffInvitationFactory()
        self.client.login(email=invitation.sender.email, password=DEFAULT_PASSWORD)
        response = self.client.get(invitation.acceptance_link, follow=True)

        self.assertEqual(reverse("account_logout"), response.wsgi_request.path)
        self.assertFalse(invitation.accepted)
        self.assertContains(response, "Un utilisateur est déjà connecté.")
