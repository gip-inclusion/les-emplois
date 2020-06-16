from django.contrib.auth import get_user_model
from django.core import mail
from django.shortcuts import reverse
from django.test import TestCase

from itou.invitations.factories import ExpiredInvitationFactory, SentInvitationFactory
from itou.invitations.models import Invitation
from itou.users.factories import DEFAULT_PASSWORD, UserFactory
from itou.www.invitations_views.forms import NewInvitationForm


class SendInvitationTest(TestCase):
    def test_send_one_invitation(self):
        user = UserFactory()
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)

        new_invitation_url = reverse("invitations_views:create")
        response = self.client.get(new_invitation_url)

        # Assert form is present
        form = NewInvitationForm(response.wsgi_request)
        self.assertContains(response, form["first_name"].label)
        self.assertContains(response, form["last_name"].label)
        self.assertContains(response, form["email"].label)

        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": "Léonie",
            "form-0-last_name": "Bathiat",
            "form-0-email": "leonie@bathiat.com",
        }

        response = self.client.post(new_invitation_url, data=data)

        invitations = Invitation.objects.count()
        self.assertEqual(invitations, 1)

        invitation = Invitation.objects.first()
        self.assertEqual(invitation.sender.pk, user.pk)

        self.assertEqual(response.status_code, 200)

        # Make sure a success message is present
        messages = list(response.context["messages"])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].level_tag, "success")

        self.assertTrue(invitation.sent)

        # Make sure an email has been sent to the invited person
        outbox_emails = [receiver for message in mail.outbox for receiver in message.to]
        self.assertIn(data["form-0-email"], outbox_emails)

    def test_send_invitation_user_already_exists(self):
        user = UserFactory()
        invited_user = UserFactory()
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)

        new_invitation_url = reverse("invitations_views:create")
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": invited_user.first_name,
            "form-0-last_name": invited_user.last_name,
            "form-0-email": invited_user.email,
        }

        response = self.client.post(new_invitation_url, data=data)
        self.assertEqual(response.status_code, 200)

        invitations = Invitation.objects.count()
        self.assertEqual(invitations, 0)

    def test_send_multiple_invitations(self):
        user = UserFactory()
        invited_user = UserFactory.build()
        second_invited_user = UserFactory.build()
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        new_invitation_url = reverse("invitations_views:create")
        response = self.client.get(new_invitation_url)

        self.assertTrue(response.context["formset"])
        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": invited_user.first_name,
            "form-0-last_name": invited_user.last_name,
            "form-0-email": invited_user.email,
            "form-1-first_name": second_invited_user.first_name,
            "form-1-last_name": second_invited_user.last_name,
            "form-1-email": second_invited_user.email,
        }

        self.client.post(new_invitation_url, data=data)
        invitations = Invitation.objects.count()
        self.assertEqual(invitations, 2)

    def test_send_multiple_invitations_duplicated_email(self):
        user = UserFactory()
        invited_user = UserFactory.build()
        second_invited_user = UserFactory.build()
        duplicated_user = UserFactory.build(email=second_invited_user.email)
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        new_invitation_url = reverse("invitations_views:create")
        response = self.client.get(new_invitation_url)

        self.assertTrue(response.context["formset"])
        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": invited_user.first_name,
            "form-0-last_name": invited_user.last_name,
            "form-0-email": invited_user.email,
            "form-1-first_name": second_invited_user.first_name,
            "form-1-last_name": second_invited_user.last_name,
            "form-1-email": second_invited_user.email,
            "form-2-first_name": duplicated_user.first_name,
            "form-2-last_name": duplicated_user.last_name,
            "form-2-email": duplicated_user.email,
        }

        response = self.client.post(new_invitation_url, data=data)
        self.assertEqual(response.status_code, 200)

        invitations = Invitation.objects.count()
        self.assertEqual(invitations, 2)


class AcceptInvitationTest(TestCase):
    def test_accept_invitation_signup(self):

        invitation = SentInvitationFactory()

        response = self.client.get(invitation.acceptance_link, follow=True)

        form_data = {"first_name": invitation.first_name, "last_name": invitation.last_name}

        # Assert data is already present and not editable
        form = response.context.get("form")

        for key, data in form_data.items():
            self.assertEqual(form.fields[key].initial, data)

        total_users_before = get_user_model().objects.count()

        # Fill in the password and send
        response = self.client.post(
            invitation.acceptance_link,
            data={**form_data, "password1": "Erls92#32", "password2": "Erls92#32"},
            follow=True,
        )

        total_users_after = get_user_model().objects.count()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.path, reverse("dashboard:index"))
        self.assertEqual((total_users_before + 1), total_users_after)

        invitation.refresh_from_db()

        self.assertTrue(invitation.accepted)
        self.assertTrue(invitation.accepted_at)

        user = get_user_model().objects.get(email=invitation.email)
        self.assertTrue(user.emailaddress_set.first().verified)

        # Make sure an email is sent to the invitation sender
        outbox_emails = [receiver for message in mail.outbox for receiver in message.to]
        self.assertIn(invitation.sender.email, outbox_emails)

    def test_accept_invitation_logout_user(self):
        logged_in_user = UserFactory()
        self.client.login(email=logged_in_user.email, password=DEFAULT_PASSWORD)
        invitation = SentInvitationFactory()
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertFalse(response.context["user"].is_authenticated)

        form_data = {"first_name": invitation.first_name, "last_name": invitation.last_name}

        response = self.client.post(
            invitation.acceptance_link,
            data={**form_data, "password1": "Erls92#32", "password2": "Erls92#32"},
            follow=True,
        )
        self.assertTrue(response.context["user"].is_authenticated)

    def test_accept_invitation_signup_changed_email(self):

        invitation = SentInvitationFactory()

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

        user = get_user_model().objects.get(email=invitation.email)
        self.assertEqual(invitation.email, user.email)

    def test_accept_invitation_signup_weak_password(self):
        invitation = SentInvitationFactory()
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

    def test_accept_expired_invitation(self):
        invitation = ExpiredInvitationFactory()

        # User wants to join our website but it's too late!
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.wsgi_request.path, reverse("invitations_views:accept", kwargs={"invitation_id": invitation.pk})
        )
        self.assertContains(response, "expirée")

    def test_accept_non_existant_invitation(self):
        invitation = Invitation(first_name="Léonie", last_name="Bathiat", email="leonie@bathiat.com")
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertEqual(response.status_code, 404)

    def test_accept_accepted_invitation(self):
        invitation = SentInvitationFactory(accepted=True)

        # User wants to join our website but it's too late!
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.wsgi_request.path, reverse("invitations_views:accept", kwargs={"invitation_id": invitation.pk})
        )
        self.assertContains(response, "acceptée")

    def test_accept_invitation_user_already_exists(self):
        user = UserFactory()
        invitation = SentInvitationFactory(first_name=user.first_name, last_name=user.last_name, email=user.email)

        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.wsgi_request.path, reverse("invitations_views:accept", kwargs={"invitation_id": invitation.pk})
        )
        self.assertContains(response, "membres")


class NewInvitationFormTest(TestCase):
    def setUp(self):
        self.data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": "Léonie",
            "form-0-last_name": "Bathiat",
            "form-0-email": "leonie@bathiat.com",
        }

    def test_send_invitation_user_already_exists(self):
        user = UserFactory()
        invited_user = UserFactory()
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        new_invitation_url = reverse("invitations_views:create")

        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": invited_user.first_name,
            "form-0-last_name": invited_user.last_name,
            "form-0-email": invited_user.email,
        }
        response = self.client.post(new_invitation_url, data=data)

        for error_dict in response.context["formset"].errors:
            for key, errors in error_dict.items():
                self.assertEqual(key, "email")
                self.assertIn("Cet utilisateur existe déjà.", errors)

    def test_send_invitation_existing_invitation(self):
        user = UserFactory()
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        new_invitation_url = reverse("invitations_views:create")
        SentInvitationFactory(sender=user, first_name="Léonie", last_name="Bathiat", email="leonie@bathiat.com")

        response = self.client.post(new_invitation_url, data=self.data)

        for error_dict in response.context["formset"].errors:
            for key, errors in error_dict.items():
                self.assertEqual(key, "email")
                self.assertIn("Cette personne a déjà été invitée.", errors)

    def test_send_invitation_expired(self):
        user = UserFactory()
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        new_invitation_url = reverse("invitations_views:create")
        invitation = ExpiredInvitationFactory(
            sender=user, first_name="Léonie", last_name="Bathiat", email="leonie@bathiat.com"
        )

        data = self.data
        response = self.client.post(new_invitation_url, data=data)

        # Make sure a success message is present
        messages = list(response.context["messages"])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].level_tag, "success")

        self.assertTrue(invitation.sent)

        # Make sure an email has been sent to the invited person
        outbox_emails = [receiver for message in mail.outbox for receiver in message.to]
        self.assertIn(self.data["form-0-email"], outbox_emails)
