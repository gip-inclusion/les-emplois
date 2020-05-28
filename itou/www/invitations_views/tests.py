from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.core import mail
from django.shortcuts import reverse
from django.test import TestCase
from django.utils import timezone

from itou.invitations.factories import ExpiredInvitationFactory, SentInvitationFactory
from itou.invitations.models import Invitation


class AcceptInvitationTest(TestCase):
    def test_accept_invitation(self):

        invitation = SentInvitationFactory()

        response = self.client.get(invitation.acceptance_link, follow=True)

        signup_form_url = reverse("signup:from_invitation", kwargs={"invitation_id": invitation.pk})

        self.assertEqual(response.redirect_chain[0][0], signup_form_url)

        self.client.get(signup_form_url)

        form_data = {"first_name": invitation.first_name, "last_name": invitation.last_name, "email": invitation.email}

        # Assert data is already present and not editable
        form = response.context_data.get("form")

        for key, data in form_data.items():
            self.assertEqual(form.initial[key], data)
            self.assertTrue(form.fields[key].widget.attrs["readonly"])

        total_users_before = get_user_model().objects.count()

        # Fill in the password and send
        response = self.client.post(
            signup_form_url, data={**form_data, "password1": "Erls92#32", "password2": "Erls92#32"}, follow=True
        )

        total_users_after = get_user_model().objects.count()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.path, reverse("dashboard:index"))
        self.assertEqual((total_users_before + 1), total_users_after)

        invitation.refresh_from_db()

        self.assertTrue(invitation.accepted)

        # Make sure an email is sent to the invitation sender
        outbox_emails = [receiver for message in mail.outbox for receiver in message.to]
        self.assertIn(invitation.sender.email, outbox_emails)

    def test_accept_expired_invitation(self):
        invitation = ExpiredInvitationFactory()

        # User wants to join our website but it's too late!
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "expirée")

    def test_accept_non_existant_invitation(self):
        invitation = Invitation(first_name="Léonie", last_name="Bathiat", email="leonie@bathiat.com")
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertEqual(response.status_code, 404)
