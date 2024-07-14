from django.core import mail
from django.shortcuts import reverse
from django.utils import timezone
from django.utils.html import escape

from itou.invitations.models import EmployerInvitation
from itou.users.enums import UserKind
from itou.www.invitations_views.forms import EmployerInvitationForm
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory
from tests.utils.test import TestCase


INVITATION_URL = reverse("invitations_views:invite_employer")


class TestSendSingleCompanyInvitation(TestCase):
    def setUp(self):
        super().setUp()
        self.company = CompanyFactory(with_membership=True)
        # The sender is a member of the company
        self.sender = self.company.members.first()
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
        self.client.force_login(self.sender)
        response = self.client.get(INVITATION_URL)

        # Assert form is present
        form = EmployerInvitationForm(sender=self.sender, company=self.company)
        self.assertContains(response, form["first_name"].label)
        self.assertContains(response, form["last_name"].label)
        self.assertContains(response, form["email"].label)

        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertContains(response, "Invitation envoyée")

        invitations = EmployerInvitation.objects.all()
        assert len(invitations) == 1

        invitation = invitations[0]
        assert invitation.sender.pk == self.sender.pk
        assert invitation.sent

        # Make sure an email has been sent to the invited person
        outbox_emails = [receiver for message in mail.outbox for receiver in message.to]
        assert self.post_data["form-0-email"] in outbox_emails

    def test_send_invitation_user_already_exists(self):
        guest = EmployerFactory(
            first_name=self.guest_data["first_name"],
            last_name=self.guest_data["last_name"],
            email=self.guest_data["email"],
        )
        self.client.force_login(self.sender)
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        assert response.status_code == 200

        # The guest will be able to join the structure
        invitations = EmployerInvitation.objects.all()
        assert len(invitations) == 1

        invitation = invitations[0]

        # At least one complete test of the invitation fields in our test suite
        assert not invitation.accepted
        assert invitation.sent_at < timezone.now()
        assert invitation.first_name == guest.first_name
        assert invitation.last_name == guest.last_name
        assert invitation.email == guest.email
        assert invitation.sender == self.sender
        assert invitation.company == self.company
        assert invitation.USER_KIND == UserKind.EMPLOYER

    def test_send_invitation_to_not_employer(self):
        user = JobSeekerFactory(**self.guest_data)
        self.client.force_login(self.sender)

        for kind in [UserKind.JOB_SEEKER, UserKind.PRESCRIBER, UserKind.LABOR_INSPECTOR]:
            user.kind = kind
            user.save()
            response = self.client.post(INVITATION_URL, data=self.post_data)

            for error_dict in response.context["formset"].errors:
                for key, _errors in error_dict.items():
                    assert key == "email"
                    assert error_dict["email"][0] == "Cet utilisateur n'est pas un employeur."

    def test_two_employers_invite_the_same_guest(self):
        # company 1 invites guest.
        self.client.force_login(self.sender)
        self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        assert EmployerInvitation.objects.count() == 1

        # company 2 invites guest as well.
        company = CompanyFactory(with_membership=True)
        sender_2 = company.members.first()
        self.client.force_login(sender_2)
        self.client.post(INVITATION_URL, data=self.post_data)
        assert EmployerInvitation.objects.count() == 2
        invitation = EmployerInvitation.objects.get(company=company)
        assert invitation.first_name == self.guest_data["first_name"]
        assert invitation.last_name == self.guest_data["last_name"]
        assert invitation.email == self.guest_data["email"]


class TestSendMultipleCompanyInvitation(TestCase):
    def setUp(self):
        self.company = CompanyFactory(with_membership=True)
        # The sender is a member of the company
        self.sender = self.company.members.first()
        # Define instances not created in DB
        self.invited_user = EmployerFactory.build()
        self.second_invited_user = EmployerFactory.build()
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
        self.client.force_login(self.sender)
        response = self.client.get(INVITATION_URL)

        assert response.context["formset"]
        response = self.client.post(INVITATION_URL, data=self.post_data)
        invitations = EmployerInvitation.objects.count()
        assert invitations == 2

        assert response.status_code == 302
        assert response.url == reverse("companies_views:members")

    def test_send_multiple_invitations_duplicated_email(self):
        self.client.force_login(self.sender)
        response = self.client.get(INVITATION_URL)

        assert response.context["formset"]
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
        invitations = EmployerInvitation.objects.count()
        assert invitations == 0


class TestSendInvitationToSpecialGuest(TestCase):
    def setUp(self):
        super().setUp()
        self.sender_company = CompanyFactory(with_membership=True)
        self.sender = self.sender_company.members.first()
        self.client.force_login(self.sender)
        self.post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
        }

    def test_invite_existing_user_with_existing_inactive_company(self):
        """
        An inactive SIAIE user (i.e. attached to a single inactive company)
        can only be ressucitated by being invited to a new company.
        We test here that this is indeed possible.
        """
        guest = CompanyFactory(convention__is_active=False, with_membership=True).members.first()
        self.post_data.update(
            {
                "form-0-first_name": guest.first_name,
                "form-0-last_name": guest.last_name,
                "form-0-email": guest.email,
            }
        )
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        assert response.status_code == 200
        assert EmployerInvitation.objects.count() == 1

    def test_invite_former_employer(self):
        """
        Admins can "deactivate" members of the organization (making the membership inactive).
        A deactivated member must be able to receive new invitations.
        """
        guest = CompanyFactory(with_membership=True).members.first()

        # Deactivate user
        membership = guest.companymembership_set.first()
        membership.deactivate_membership_by_user(self.sender_company.members.first())
        membership.save()

        self.post_data.update(
            {
                "form-0-first_name": guest.first_name,
                "form-0-last_name": guest.last_name,
                "form-0-email": guest.email,
            }
        )
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        assert response.status_code == 200
        assert EmployerInvitation.objects.count() == 1

    def test_invite_existing_user_is_prescriber(self):
        guest = PrescriberOrganizationWithMembershipFactory().members.first()
        self.client.force_login(self.sender)
        self.post_data.update(
            {
                "form-0-first_name": guest.first_name,
                "form-0-last_name": guest.last_name,
                "form-0-email": guest.email,
            }
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        # The form is invalid
        assert not response.context["formset"].is_valid()
        assert "email" in response.context["formset"].errors[0]
        assert response.context["formset"].errors[0]["email"][0] == "Cet utilisateur n'est pas un employeur."
        assert EmployerInvitation.objects.count() == 0

    def test_invite_existing_user_is_job_seeker(self):
        guest = JobSeekerFactory()
        self.client.force_login(self.sender)
        self.post_data.update(
            {
                "form-0-first_name": guest.first_name,
                "form-0-last_name": guest.last_name,
                "form-0-email": guest.email,
            }
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        # Make sure form is invalid
        assert not response.context["formset"].is_valid()
        assert "email" in response.context["formset"].errors[0]
        assert response.context["formset"].errors[0]["email"][0] == "Cet utilisateur n'est pas un employeur."
        assert EmployerInvitation.objects.count() == 0

    def test_already_a_member(self):
        # The invited user is already a member
        CompanyMembershipFactory(company=self.sender_company, is_admin=False)
        guest = self.sender_company.members.exclude(email=self.sender.email).first()
        self.client.force_login(self.sender)
        self.post_data.update(
            {
                "form-0-first_name": guest.first_name,
                "form-0-last_name": guest.last_name,
                "form-0-email": guest.email,
            }
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        # Make sure form is invalid
        assert not response.context["formset"].is_valid()
        assert "email" in response.context["formset"].errors[0]
        assert (
            response.context["formset"].errors[0]["email"][0] == "Cette personne fait déjà partie de votre structure."
        )

        assert EmployerInvitation.objects.count() == 0
