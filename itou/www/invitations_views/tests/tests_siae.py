from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core import mail
from django.shortcuts import reverse
from django.test import TestCase

from itou.invitations.factories import SiaeSentInvitationFactory
from itou.invitations.models import SiaeStaffInvitation
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeWith2MembershipsFactory
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, UserFactory
from itou.www.invitations_views.forms import NewSiaeStaffInvitationForm


"""
#####################################################################
############################## Views ################################
#####################################################################
"""


class TestSendSiaeInvitation(TestCase):
    def setUp(self):
        self.siae = SiaeWith2MembershipsFactory()
        self.sender = self.siae.members.first()
        self.guest = UserFactory.build(first_name="Léonie", last_name="Bathiat")
        self.post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": self.guest.first_name,
            "form-0-last_name": self.guest.last_name,
            "form-0-email": self.guest.email,
        }
        self.invitations_model = SiaeStaffInvitation
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.send_invitation_url = reverse("invitations_views:invite_siae_staff")

    def tearDown(self):
        invitation_query = self.invitations_model.objects.filter(siae=self.siae)
        self.assertTrue(invitation_query.exists())
        invitation = invitation_query.first()
        self.assertEqual(invitation.first_name, self.guest.first_name)
        self.assertEqual(invitation.last_name, self.guest.last_name)
        self.assertEqual(invitation.email, self.guest.email)

    def test_invite_not_existing_user(self):
        self.client.post(self.send_invitation_url, data=self.post_data)

    def test_invite_existing_user_is_employer(self):
        self.guest = SiaeWith2MembershipsFactory().members.first()
        self.post_data["form-0-first_name"] = self.guest.first_name
        self.post_data["form-0-last_name"] = self.guest.last_name
        self.post_data["form-0-email"] = self.guest.email
        self.client.post(self.send_invitation_url, data=self.post_data)


class TestSendSiaeInvitationExceptions(TestCase):
    def setUp(self):
        self.siae = SiaeWith2MembershipsFactory()
        self.sender = self.siae.members.first()
        self.send_invitation_url = reverse("invitations_views:invite_siae_staff")
        self.invitations_model = SiaeStaffInvitation

    def tearDown(self):
        invitation_query = self.invitations_model.objects.filter(siae=self.siae)
        self.assertFalse(invitation_query.exists())

    def test_invite_existing_user_is_prescriber(self):
        guest = PrescriberOrganizationWithMembershipFactory().members.first()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": guest.first_name,
            "form-0-last_name": guest.last_name,
            "form-0-email": guest.email,
        }
        response = self.client.post(self.send_invitation_url, data=post_data)
        # Make sure form is not valid
        self.assertFalse(response.context["formset"].is_valid())
        self.assertTrue(response.context["formset"].errors[0].get("email"))

    def test_invite_existing_user_is_job_seeker(self):
        guest = JobSeekerFactory()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": guest.first_name,
            "form-0-last_name": guest.last_name,
            "form-0-email": guest.email,
        }
        response = self.client.post(self.send_invitation_url, data=post_data)
        # Make sure form is not valid
        self.assertFalse(response.context["formset"].is_valid())
        self.assertTrue(response.context["formset"].errors[0].get("email"))


class TestAcceptSiaeInvitation(TestCase):
    def setUp(self):
        self.siae = SiaeWith2MembershipsFactory()
        self.sender = self.siae.members.first()
        self.invitation = SiaeSentInvitationFactory(sender=self.sender, siae=self.siae)
        self.join_siae_url = reverse("invitations_views:join_siae", kwargs={"invitation_id": self.invitation.pk})
        self.user = get_user_model()

    def tearDown(self):
        response = self.client.post(self.join_siae_url, follow=True)

        self.user.refresh_from_db()
        self.invitation.refresh_from_db()
        self.assertTrue(self.user.is_siae_staff)
        self.assertTrue(self.invitation.accepted)
        self.assertTrue(self.invitation.accepted_at)
        self.assertEqual(self.siae.members.count(), 3)

        self.assertEqual(reverse("dashboard:index"), response.wsgi_request.path)
        # Make sure there's a welcome message.
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)

        # Two e-mails are sent: one to the invitation sender
        # and a second one to the SIAE members.
        self.assertEqual(len(mail.outbox), 2)

        # Make sure an email is sent to the invitation sender
        outbox_emails = [receiver for message in mail.outbox for receiver in message.to]
        self.assertIn(self.invitation.sender.email, outbox_emails)

    def test_accept_siae_invitation(self):
        response = self.client.get(self.invitation.acceptance_link, follow=True)
        self.assertIn(response.wsgi_request.path, self.invitation.acceptance_link)

        form_data = {
            "first_name": self.invitation.first_name,
            "last_name": self.invitation.last_name,
            "password1": "Erls92#32",
            "password2": "Erls92#32",
        }

        response = self.client.post(self.invitation.acceptance_link, data=form_data, follow=True)

        self.user = get_user_model().objects.get(email=self.invitation.email)
        self.assertEqual(self.join_siae_url, response.wsgi_request.path)
        self.assertFalse(self.user.is_siae_staff)
        self.assertFalse(self.invitation.accepted)

        # Make sure he still can see the dashboard
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 200)

    def test_accept_existing_user_is_employer(self):
        self.user = SiaeWith2MembershipsFactory().members.first()
        self.invitation = SiaeSentInvitationFactory(
            sender=self.sender,
            siae=self.siae,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
            email=self.user.email,
        )
        self.join_siae_url = reverse("invitations_views:join_siae", kwargs={"invitation_id": self.invitation.pk})

        self.client.login(email=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.invitation.acceptance_link, follow=True)

        self.assertEqual(self.join_siae_url, response.wsgi_request.path)
        self.assertFalse(self.invitation.accepted)

    def test_accept_existing_user_not_logged_in(self):
        self.user = SiaeWith2MembershipsFactory().members.first()
        # The user verified its email
        EmailAddress(user_id=self.user.pk, email=self.user.email, verified=True, primary=True).save()
        self.invitation = SiaeSentInvitationFactory(
            sender=self.sender,
            siae=self.siae,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
            email=self.user.email,
        )
        self.join_siae_url = reverse("invitations_views:join_siae", kwargs={"invitation_id": self.invitation.pk})

        response = self.client.get(self.invitation.acceptance_link, follow=True)

        self.assertIn(reverse("account_login"), response.wsgi_request.get_full_path())
        self.assertFalse(self.invitation.accepted)

        response = self.client.post(
            response.wsgi_request.get_full_path(),
            data={"login": self.user.email, "password": DEFAULT_PASSWORD},
            follow=True,
        )
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertIn(response.wsgi_request.path, self.join_siae_url)


class TestAcceptSiaeInvitationExceptions(TestCase):
    def setUp(self):
        self.siae = SiaeWith2MembershipsFactory()
        self.sender = self.siae.members.first()
        self.invitation = SiaeSentInvitationFactory(sender=self.sender, siae=self.siae)
        self.join_siae_url = reverse("invitations_views:join_siae", kwargs={"invitation_id": self.invitation.pk})
        self.user = get_user_model()

    def test_accept_existing_user_is_not_employer(self):
        self.user = PrescriberOrganizationWithMembershipFactory().members.first()
        self.invitation = SiaeSentInvitationFactory(
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

    # def test_accept_invited_user_is_already_a_member(self):
    # """
    # This should never happen as the detection should be made when the invitation is sent.
    # """
    #     self.user = self.siae.members.exclude(email=self.sender.email).first()
    #     self.invitation = SiaeSentInvitationFactory(
    #         sender=self.sender,
    #         siae=self.siae,
    #         first_name=self.user.first_name,
    #         last_name=self.user.last_name,
    #         email=self.user.email
    #     )
    #     self.join_siae_url = reverse("invitations_views:join_siae", kwargs={"invitation_id": self.invitation.pk})

    #     self.client.login(email=self.user.email, password=DEFAULT_PASSWORD)
    #     response = self.client.get(self.invitation.acceptance_link, follow=True)

    #     self.assertEqual(
    #         self.join_siae_url,
    #         response.wsgi_request.path
    #     )
    #     self.assertNotContains(response, "join_siae_form")
    #     self.assertFalse(self.invitation.accepted)
    #     messages = list(get_messages(response.wsgi_request))
    #     self.assertEqual(len(messages), 1)


"""
#####################################################################
############################## Forms ################################
#####################################################################
"""


class TestNewSiaeStaffForm(TestCase):
    def test_new_siae_staff_form(self):
        siae = SiaeWith2MembershipsFactory()
        sender = siae.members.first()
        form = NewSiaeStaffInvitationForm(sender=sender, siae=siae)
        form.save()
        invitation = SiaeStaffInvitation.objects.get(sender=sender)
        self.assertEqual(invitation.siae.pk, siae.pk)
