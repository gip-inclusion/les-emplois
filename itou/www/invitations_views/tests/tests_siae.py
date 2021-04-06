from allauth.account.models import EmailAddress
from django.contrib.messages import get_messages
from django.core import mail
from django.shortcuts import reverse
from django.test import TestCase

from itou.invitations.factories import SiaeSentInvitationFactory
from itou.invitations.models import SiaeStaffInvitation
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeWith2MembershipsFactory
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, UserFactory
from itou.users.models import User
from itou.utils.perms.siae import get_current_siae_or_404
from itou.www.invitations_views.forms import NewSiaeStaffInvitationForm


#####################################################################
############################## Views ################################
#####################################################################


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
        response = self.client.post(self.send_invitation_url, data=self.post_data, follow=True)
        self.assertContains(response, "Votre invitation a été envoyée par e-mail")

    def test_invite_existing_user_with_existing_inactive_siae(self):
        """
        An inactive siae user (i.e. attached to a single inactive siae)
        can only be ressucitated by being invited to a new siae.
        We test here that this is indeed possible.
        """
        self.guest = SiaeWith2MembershipsFactory(convention__is_active=False).members.first()
        self.post_data["form-0-first_name"] = self.guest.first_name
        self.post_data["form-0-last_name"] = self.guest.last_name
        self.post_data["form-0-email"] = self.guest.email
        response = self.client.post(self.send_invitation_url, data=self.post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(last_url, reverse("invitations_views:invite_siae_staff"))

    def test_two_employers_invite_the_same_guest(self):
        # SIAE 1 invites guest.
        self.client.post(self.send_invitation_url, data=self.post_data)

        # SIAE 2 invites guest as well.
        siae_2 = SiaeWith2MembershipsFactory()
        siae_2_sender = siae_2.members.first()
        self.client.login(email=siae_2_sender.email, password=DEFAULT_PASSWORD)
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": self.guest.first_name,
            "form-0-last_name": self.guest.last_name,
            "form-0-email": self.guest.email,
        }
        self.client.post(self.send_invitation_url, data=post_data)
        invitation_query = self.invitations_model.objects.filter(siae=siae_2)
        self.assertTrue(invitation_query.exists())
        invitation = invitation_query.first()
        self.assertEqual(invitation.first_name, self.guest.first_name)
        self.assertEqual(invitation.last_name, self.guest.last_name)
        self.assertEqual(invitation.email, self.guest.email)

        # SIAE 1 should be able to refresh the invitation.
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.client.post(self.send_invitation_url, data=self.post_data)

    def test_invite_former_siae_member(self):
        """
        Admins can "deactivate" members of the organization (making the membership inactive).
        A deactivated member must be able to receive new invitations.
        """
        self.guest = SiaeWith2MembershipsFactory().members.first()

        # Deactivate user
        membership = self.guest.siaemembership_set.first()
        membership.toggle_user_membership(self.siae.members.first())
        membership.save()

        self.post_data["form-0-first_name"] = self.guest.first_name
        self.post_data["form-0-last_name"] = self.guest.last_name
        self.post_data["form-0-email"] = self.guest.email
        response = self.client.post(self.send_invitation_url, data=self.post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(last_url, reverse("invitations_views:invite_siae_staff"))


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

    def test_already_a_member(self):
        # The invited user is already a member
        guest = self.siae.members.exclude(email=self.sender.email).first()
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
        self.user = User
        self.response = None

    def tearDown(self):
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

    def test_accept_existing_user_is_employer(self):
        self.user = SiaeWith2MembershipsFactory().members.first()
        self.invitation = SiaeSentInvitationFactory(
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

    def test_accept_existing_user_with_existing_inactive_siae(self):
        """
        An inactive siae user (i.e. attached to a single inactive siae)
        can only be ressucitated by being invited to a new siae.
        We test here that this is indeed possible.
        """
        self.user = SiaeWith2MembershipsFactory(convention__is_active=False).members.first()
        self.invitation = SiaeSentInvitationFactory(
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
        response = self.client.get(self.invitation.acceptance_link, follow=True)

        self.assertIn(reverse("account_login"), response.wsgi_request.get_full_path())
        self.assertFalse(self.invitation.accepted)

        self.response = self.client.post(
            response.wsgi_request.get_full_path(),
            data={"login": self.user.email, "password": DEFAULT_PASSWORD},
            follow=True,
        )
        self.assertTrue(self.response.wsgi_request.user.is_authenticated)


class TestAcceptSiaeInvitationExceptions(TestCase):
    def setUp(self):
        self.siae = SiaeWith2MembershipsFactory()
        self.sender = self.siae.members.first()
        self.invitation = SiaeSentInvitationFactory(sender=self.sender, siae=self.siae)
        self.user = User

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


#####################################################################
############################## Forms ################################
#####################################################################


class TestNewSiaeStaffForm(TestCase):
    def test_new_siae_staff_form(self):
        siae = SiaeWith2MembershipsFactory()
        sender = siae.members.first()
        form = NewSiaeStaffInvitationForm(sender=sender, siae=siae)
        form.save()
        invitation = SiaeStaffInvitation.objects.get(sender=sender)
        self.assertEqual(invitation.siae.pk, siae.pk)
