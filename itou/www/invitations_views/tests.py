from django.contrib.auth import get_user_model
from django.shortcuts import reverse
from django.test import TestCase

from itou.invitations.factories import SentInvitationFactory


class AcceptInvitationTest(TestCase):
    def test_accept_invitation(self):

        invitation = SentInvitationFactory()

        acceptance_link = invitation.acceptance_link
        response = self.client.get(acceptance_link, follow=True)

        signup_form_url = reverse("signup:from_invitation", kwargs={"encoded_invitation_id": invitation.encoded_pk})

        self.assertEqual(response.redirect_chain[0][0], signup_form_url)

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
