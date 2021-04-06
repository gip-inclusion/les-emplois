from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
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
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.www.invitations_views.forms import NewPrescriberWithOrgInvitationForm


#####################################################################
############################## Views ################################
#####################################################################


class TestSendPrescriberWithOrgInvitation(TestCase):
    def setUp(self):
        self.org = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganization.Kind.CAP_EMPLOI)
        self.sender = self.org.members.first()
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
        self.invitations_model = PrescriberWithOrgInvitation
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.send_invitation_url = reverse("invitations_views:invite_prescriber_with_org")

    def tearDown(self):
        invitation_query = self.invitations_model.objects.filter(organization=self.org)
        self.assertTrue(invitation_query.exists())
        invitation = invitation_query.first()
        self.assertEqual(invitation.first_name, self.guest.first_name)
        self.assertEqual(invitation.last_name, self.guest.last_name)
        self.assertEqual(invitation.email, self.guest.email)
        self.assertEqual(self.response.status_code, 200)
        # The user is redirected to the same page.
        self.assertEqual(self.response.wsgi_request.path, self.send_invitation_url)

    def test_invite_not_existing_user(self):
        self.response = self.client.post(self.send_invitation_url, data=self.post_data, follow=True)

    def test_invite_existing_user_is_prescriber_without_org(self):
        self.guest = PrescriberFactory()
        self.post_data["form-0-first_name"] = self.guest.first_name
        self.post_data["form-0-last_name"] = self.guest.last_name
        self.post_data["form-0-email"] = self.guest.email
        self.response = self.client.post(self.send_invitation_url, data=self.post_data, follow=True)

    def test_pe_organization_invitation_successful(self):
        self.client.logout()

        self.org = PrescriberPoleEmploiFactory()
        self.org.members.add(PrescriberFactory())
        self.sender = self.org.members.first()
        self.guest = UserFactory.build(email=f"sabine.lagrange{settings.POLE_EMPLOI_EMAIL_SUFFIX}")
        self.post_data["form-0-first_name"] = self.guest.first_name
        self.post_data["form-0-last_name"] = self.guest.last_name
        self.post_data["form-0-email"] = self.guest.email

        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.response = self.client.post(self.send_invitation_url, data=self.post_data, follow=True)

    def test_invite_former_member(self):
        """
        Admins can "deactivate" members of the organization (making the membership inactive).
        A deactivated member must be able to receive new invitations.
        """
        # Invite user (part 1)
        self.guest = PrescriberFactory()
        self.post_data["form-0-first_name"] = self.guest.first_name
        self.post_data["form-0-last_name"] = self.guest.last_name
        self.post_data["form-0-email"] = self.guest.email
        self.response = self.client.post(self.send_invitation_url, data=self.post_data, follow=True)
        # Deactivate user
        self.org.members.add(self.guest)
        self.guest.save()
        membership = self.guest.prescribermembership_set.first()
        membership.toggle_user_membership(self.org.members.first())
        membership.save()
        self.assertFalse(self.guest in self.org.active_members)
        # Invite user (the revenge)
        self.response = self.client.post(self.send_invitation_url, data=self.post_data, follow=True)


class TestSendPrescriberWithOrgInvitationExceptions(TestCase):
    def setUp(self):
        self.org = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganization.Kind.CAP_EMPLOI)
        self.sender = self.org.members.first()
        self.send_invitation_url = reverse("invitations_views:invite_prescriber_with_org")
        self.invitations_model = PrescriberWithOrgInvitation
        self.post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
        }

    def tearDown(self):
        invitation_query = self.invitations_model.objects.filter(organization=self.org)
        self.assertFalse(invitation_query.exists())
        self.assertEqual(self.response.status_code, 200)

    def test_invite_existing_user_is_employer(self):
        guest = SiaeWithMembershipFactory().members.first()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data.update(
            {"form-0-first_name": guest.first_name, "form-0-last_name": guest.last_name, "form-0-email": guest.email}
        )
        self.response = self.client.post(self.send_invitation_url, data=self.post_data)
        # Make sure form is not valid
        self.assertFalse(self.response.context["formset"].is_valid())
        self.assertTrue(self.response.context["formset"].errors[0].get("email"))

    def test_invite_existing_user_is_job_seeker(self):
        guest = JobSeekerFactory()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data.update(
            {"form-0-first_name": guest.first_name, "form-0-last_name": guest.last_name, "form-0-email": guest.email}
        )
        self.response = self.client.post(self.send_invitation_url, data=self.post_data)
        # Make sure form is not valid
        self.assertFalse(self.response.context["formset"].is_valid())
        self.assertTrue(self.response.context["formset"].errors[0].get("email"))

    def test_already_a_member(self):
        # The invited user is already a member
        self.org.members.add(PrescriberFactory())
        guest = self.org.members.exclude(email=self.sender.email).first()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data.update(
            {"form-0-first_name": guest.first_name, "form-0-last_name": guest.last_name, "form-0-email": guest.email}
        )
        self.response = self.client.post(self.send_invitation_url, data=self.post_data)
        # Make sure form is not valid
        self.assertFalse(self.response.context["formset"].is_valid())
        self.assertTrue(self.response.context["formset"].errors[0].get("email"))

    def test_pe_organization_invitation_unsuccessful(self):
        self.org = PrescriberPoleEmploiFactory()
        self.org.members.add(PrescriberFactory())
        self.sender = self.org.members.first()
        guest = UserFactory.build()
        self.client.login(email=self.sender.email, password=DEFAULT_PASSWORD)
        self.post_data.update(
            {"form-0-first_name": guest.first_name, "form-0-last_name": guest.last_name, "form-0-email": guest.email}
        )
        self.response = self.client.post(self.send_invitation_url, data=self.post_data)
        # Make sure form is not valid
        self.assertFalse(self.response.context["formset"].is_valid())
        self.assertTrue(self.response.context["formset"].errors[0].get("email"))


class TestAcceptPrescriberWithOrgInvitation(TestCase):
    def setUp(self):
        self.org = PrescriberOrganizationWithMembershipFactory()
        # Create a second member to make sure emails are also
        # sent to regular members
        self.org.members.add(PrescriberFactory())
        self.org.save()
        self.sender = self.org.members.first()
        self.invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.org)
        self.user = get_user_model()
        self.response = None

    def tearDown(self):
        self.assertEqual(self.response.status_code, 200)
        self.user.refresh_from_db()
        self.invitation.refresh_from_db()
        self.assertTrue(self.user.is_prescriber)
        self.assertTrue(self.invitation.accepted)
        self.assertTrue(self.invitation.accepted_at)
        self.assertEqual(self.org.members.count(), 3)

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
        response = self.client.get(self.invitation.acceptance_link, follow=True)
        self.assertIn(response.wsgi_request.path, self.invitation.acceptance_link)

        form_data = {
            "first_name": self.invitation.first_name,
            "last_name": self.invitation.last_name,
            "password1": "Erls92#32",
            "password2": "Erls92#32",
        }

        self.response = self.client.post(self.invitation.acceptance_link, data=form_data, follow=True)

        self.user = get_user_model().objects.get(email=self.invitation.email)

    def test_accept_existing_user_is_prescriber_without_org(self):
        self.user = PrescriberFactory()
        self.invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.org,
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
            organization=self.org,
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
            organization=self.org,
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
        self.org = PrescriberOrganizationWithMembershipFactory()
        self.sender = self.org.members.first()
        self.invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.org)
        self.user = get_user_model()

    def test_existing_user_is_not_prescriber(self):
        self.user = SiaeWithMembershipFactory().members.first()
        self.invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.org,
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


#####################################################################
############################## Forms ################################
#####################################################################


class TestNewPrescriberOrganizationForm(TestCase):
    def test_new_prescriber_with_org_form(self):
        org = PrescriberOrganizationWithMembershipFactory()
        sender = org.members.first()
        form = NewPrescriberWithOrgInvitationForm(sender=sender, organization=org)
        invitation = form.save()
        self.assertEqual(invitation.sender, sender)
        self.assertEqual(invitation.organization.pk, org.pk)
