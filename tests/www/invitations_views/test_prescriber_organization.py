from datetime import timedelta
from urllib.parse import urlencode

import pytest
import respx
from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib import messages
from django.core import mail
from django.shortcuts import reverse
from django.test import Client
from django.utils.html import escape
from pytest_django.asserts import assertRedirects

from itou.invitations.models import PrescriberWithOrgInvitation
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.urls import add_url_params
from tests.companies.factories import CompanyFactory
from tests.invitations.factories import PrescriberWithOrgSentInvitationFactory
from tests.openid_connect.inclusion_connect.test import InclusionConnectBaseTestCase
from tests.openid_connect.inclusion_connect.tests import OIDC_USERINFO, mock_oauth_dance
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory, PrescriberPoleEmploiFactory
from tests.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, PrescriberFactory
from tests.utils.test import TestCase, assertMessages


POST_DATA = {
    "form-TOTAL_FORMS": "1",
    "form-INITIAL_FORMS": "0",
    "form-MIN_NUM_FORMS": "",
    "form-MAX_NUM_FORMS": "",
}

INVITATION_URL = reverse("invitations_views:invite_prescriber_with_org")


class TestSendPrescriberWithOrgInvitation(TestCase):
    def setUp(self):
        super().setUp()
        self.organization = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganizationKind.CAP_EMPLOI)
        self.sender = self.organization.members.first()
        self.guest_data = {"first_name": "Léonie", "last_name": "Bathiat", "email": "leonie@example.com"}
        self.post_data = POST_DATA | {
            "form-0-first_name": self.guest_data["first_name"],
            "form-0-last_name": self.guest_data["last_name"],
            "form-0-email": self.guest_data["email"],
        }
        self.client.force_login(self.sender)

    def assert_created_invitation(self):
        invitation = PrescriberWithOrgInvitation.objects.get(organization=self.organization)
        assert invitation.first_name == self.post_data["form-0-first_name"]
        assert invitation.last_name == self.post_data["form-0-last_name"]
        assert invitation.email == self.post_data["form-0-email"]

    def test_invite_not_existing_user(self):
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertRedirects(response, INVITATION_URL)
        self.assert_created_invitation()

    def test_invite_not_existing_user_with_prefill(self):
        response = self.client.get(
            INVITATION_URL, data={"first_name": "Emma", "last_name": "Watson", "email": "emma@example.com"}
        )
        # The form is prefilled with GET params (if valid)
        self.assertContains(response, "Emma")

    def test_invite_existing_user_is_prescriber_without_org(self):
        guest = PrescriberFactory()
        self.post_data["form-0-first_name"] = guest.first_name
        self.post_data["form-0-last_name"] = guest.last_name
        self.post_data["form-0-email"] = guest.email
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertRedirects(response, INVITATION_URL)
        self.assert_created_invitation()

    def test_invite_former_member(self):
        """
        Admins can "deactivate" members of the organization (making the membership inactive).
        A deactivated member must be able to receive new invitations.
        """
        # Invite user (part 1)
        guest = PrescriberFactory()
        self.post_data["form-0-first_name"] = guest.first_name
        self.post_data["form-0-last_name"] = guest.last_name
        self.post_data["form-0-email"] = guest.email
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertRedirects(response, INVITATION_URL)
        self.assert_created_invitation()

        # Deactivate user
        self.organization.members.add(guest)
        guest.save()
        membership = guest.prescribermembership_set.first()
        membership.deactivate_membership_by_user(self.organization.members.first())
        membership.save()
        assert guest not in self.organization.active_members
        # Invite user (the revenge)
        response = self.client.post(INVITATION_URL, data=self.post_data, follow=True)
        self.assertRedirects(response, INVITATION_URL)
        invitations_count = PrescriberWithOrgInvitation.objects.filter(organization=self.organization).count()
        assert invitations_count == 2


class TestSendPrescriberWithOrgInvitationExceptions(TestCase):
    def setUp(self):
        super().setUp()
        self.organization = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganizationKind.CAP_EMPLOI)
        self.sender = self.organization.members.first()
        self.post_data = POST_DATA

    def assert_invalid_user(self, response, reason):
        assert not response.context["formset"].is_valid()
        assert response.context["formset"].errors[0]["email"][0] == reason
        assert not PrescriberWithOrgInvitation.objects.exists()

    def test_invite_existing_user_is_employer(self):
        guest = CompanyFactory(with_membership=True).members.first()
        self.client.force_login(self.sender)
        self.post_data.update(
            {"form-0-first_name": guest.first_name, "form-0-last_name": guest.last_name, "form-0-email": guest.email}
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        assert response.status_code == 200
        self.assert_invalid_user(response, "Cet utilisateur n'est pas un prescripteur.")

    def test_invite_existing_user_is_job_seeker(self):
        guest = JobSeekerFactory()
        self.client.force_login(self.sender)
        self.post_data.update(
            {"form-0-first_name": guest.first_name, "form-0-last_name": guest.last_name, "form-0-email": guest.email}
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        assert response.status_code == 200
        self.assert_invalid_user(response, "Cet utilisateur n'est pas un prescripteur.")

    def test_already_a_member(self):
        # The invited user is already a member
        self.organization.members.add(PrescriberFactory())
        guest = self.organization.members.exclude(email=self.sender.email).first()
        self.client.force_login(self.sender)
        self.post_data.update(
            {"form-0-first_name": guest.first_name, "form-0-last_name": guest.last_name, "form-0-email": guest.email}
        )
        response = self.client.post(INVITATION_URL, data=self.post_data)
        assert response.status_code == 200
        self.assert_invalid_user(response, "Cette personne fait déjà partie de votre organisation.")


class TestPEOrganizationInvitation:
    @pytest.mark.parametrize(
        "suffix",
        [
            global_constants.POLE_EMPLOI_EMAIL_SUFFIX,
            global_constants.FRANCE_TRAVAIL_EMAIL_SUFFIX,
        ],
    )
    def test_successful(self, client, suffix):
        organization = PrescriberPoleEmploiFactory()
        organization.members.add(PrescriberFactory())
        sender = organization.members.first()
        guest = PrescriberFactory.build(email=f"sabine.lagrange{suffix}")
        post_data = POST_DATA | {
            "form-0-first_name": guest.first_name,
            "form-0-last_name": guest.last_name,
            "form-0-email": guest.email,
        }
        client.force_login(sender)
        response = client.post(INVITATION_URL, data=post_data, follow=True)
        assertRedirects(response, INVITATION_URL)

    def test_unsuccessful(self, client):
        organization = PrescriberPoleEmploiFactory()
        organization.members.add(PrescriberFactory())
        sender = organization.members.first()
        client.force_login(sender)
        post_data = POST_DATA | {
            "form-0-first_name": "René",
            "form-0-last_name": "Boucher",
            "form-0-email": "rene@example.com",
        }

        response = client.post(INVITATION_URL, data=post_data)
        # Make sure form is invalid
        assert not response.context["formset"].is_valid()
        assert (
            response.context["formset"].errors[0]["email"][0]
            == "L'adresse e-mail doit être une adresse Pôle emploi ou France Travail."
        )


class TestAcceptPrescriberWithOrgInvitation(InclusionConnectBaseTestCase):
    def setUp(self):
        super().setUp()
        self.organization = PrescriberOrganizationWithMembershipFactory()
        # Create a second member to make sure emails are also
        # sent to regular members
        self.organization.members.add(PrescriberFactory())
        self.organization.save()
        self.sender = self.organization.members.first()

    def assert_invitation_is_accepted(self, response, user, invitation, new_user=True):
        if new_user:
            self.assertRedirects(response, reverse("welcoming_tour:index"))
        elif user.identity_provider == IdentityProvider.DJANGO:
            self.assertRedirects(response, reverse("dashboard:activate_ic_account"))
        else:
            self.assertRedirects(response, reverse("dashboard:index"))

        user.refresh_from_db()
        invitation.refresh_from_db()
        assert user.kind == UserKind.PRESCRIBER

        assert invitation.accepted
        assert invitation.accepted_at
        assert self.organization.members.count() == 3

        # Make sure there's a welcome message.
        self.assertContains(
            response, escape(f"Vous êtes désormais membre de l'organisation {self.organization.display_name}.")
        )

        # A confirmation e-mail is sent to the invitation sender.
        assert len(mail.outbox) == 1
        assert len(mail.outbox[0].to) == 1
        assert invitation.sender.email == mail.outbox[0].to[0]

        # Assert the user sees his new organization dashboard.
        current_org = get_current_org_or_404(response.wsgi_request)
        # A user can be member of one or more organizations
        assert current_org in user.prescriberorganization_set.all()

    @respx.mock
    def test_accept_prescriber_org_invitation(self):
        invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.organization)
        response = self.client.get(invitation.acceptance_link)
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_prescriber_organization", args=(invitation.pk,))
        params = {
            "user_kind": UserKind.PRESCRIBER,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        # Singup fails on Inclusion Connect with email different than the one from the invitation
        response = mock_oauth_dance(
            self.client,
            UserKind.PRESCRIBER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
            expected_redirect_url=add_url_params(reverse("inclusion_connect:logout"), {"redirect_url": previous_url}),
        )
        # Inclusion connect redirects to previous_url
        response = self.client.get(previous_url, follow=True)
        # Signup should have failed : as the email used in IC isn't the one from the invitation
        assertMessages(
            response,
            [
                (
                    messages.ERROR,
                    "L’adresse e-mail que vous avez utilisée pour vous connecter avec "
                    "Inclusion Connect (michel@lestontons.fr) ne correspond pas à "
                    f"l’adresse e-mail de l’invitation ({invitation.email}).",
                )
            ],
        )
        assert not User.objects.filter(email=invitation.email).exists()

        # Singup works on Inclusion Connect with the correct email
        invitation.email = OIDC_USERINFO["email"]
        invitation.save()
        response = mock_oauth_dance(
            self.client,
            UserKind.PRESCRIBER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation)

    @respx.mock
    def test_accept_prescriber_org_invitation_returns_on_other_browser(self):
        invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.organization)
        response = self.client.get(invitation.acceptance_link)
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_prescriber_organization", args=(invitation.pk,))
        params = {
            "user_kind": UserKind.PRESCRIBER,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        other_client = Client()
        invitation.email = OIDC_USERINFO["email"]
        invitation.save()
        response = mock_oauth_dance(
            self.client,
            UserKind.PRESCRIBER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
            other_client=other_client,
        )
        # Follow the redirection.
        response = other_client.get(response.url, follow=True)
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation)

    def test_accept_existing_user_is_prescriber_without_org(self):
        user = PrescriberFactory(has_completed_welcoming_tour=True)
        invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        self.client.force_login(user)
        response = self.client.get(invitation.acceptance_link, follow=True)
        # /invitations/<uui>/join_company then /welcoming_tour/index
        assert len(response.redirect_chain) == 2
        self.assert_invitation_is_accepted(response, user, invitation, new_user=False)

    def test_accept_existing_user_email_different_case(self):
        user = PrescriberFactory(has_completed_welcoming_tour=True, email="HEY@example.com")
        invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=user.first_name,
            last_name=user.last_name,
            email="hey@example.com",
        )
        self.client.force_login(user)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assert_invitation_is_accepted(response, user, invitation, new_user=False)

    def test_accept_existing_user_belongs_to_another_organization(self):
        user = PrescriberOrganizationWithMembershipFactory().members.first()
        user.has_completed_welcoming_tour = True
        user.save()
        invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        self.client.force_login(user)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assert_invitation_is_accepted(response, user, invitation, new_user=False)

    @respx.mock
    def test_accept_existing_user_not_logged_in_using_IC(self):
        invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.organization)
        user = PrescriberFactory(email=OIDC_USERINFO["email"], has_completed_welcoming_tour=True)
        # The user verified its email
        EmailAddress(user_id=user.pk, email=user.email, verified=True, primary=True).save()
        invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        response = self.client.get(invitation.acceptance_link, follow=True)
        assert reverse("login:prescriber") in response.wsgi_request.get_full_path()
        assert not invitation.accepted
        next_url = reverse("invitations_views:join_prescriber_organization", args=(invitation.pk,))
        previous_url = f"{reverse('login:prescriber')}?{urlencode({'next': next_url})}"
        params = {
            "user_kind": UserKind.PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        response = mock_oauth_dance(
            self.client,
            UserKind.PRESCRIBER,
            user_email=user.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)

        assert response.context["user"].is_authenticated
        self.assert_invitation_is_accepted(response, user, invitation, new_user=False)

    def test_accept_existing_user_not_logged_in_using_django_auth(self):
        invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.organization)
        user = PrescriberFactory(has_completed_welcoming_tour=True, identity_provider="DJANGO")
        # The user verified its email
        EmailAddress(user_id=user.pk, email=user.email, verified=True, primary=True).save()
        invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        response = self.client.get(invitation.acceptance_link, follow=True)
        assert reverse("login:prescriber") in response.wsgi_request.get_full_path()
        assert not invitation.accepted

        response = self.client.post(
            response.wsgi_request.get_full_path(),
            data={"login": user.email, "password": DEFAULT_PASSWORD},
            follow=True,
        )
        assert response.context["user"].is_authenticated
        self.assert_invitation_is_accepted(response, user, invitation, new_user=False)


class TestAcceptPrescriberWithOrgInvitationExceptions(TestCase):
    def setUp(self):
        super().setUp()
        self.organization = PrescriberOrganizationWithMembershipFactory()
        self.sender = self.organization.members.first()

    def test_existing_user_is_not_prescriber(self):
        user = CompanyFactory(with_membership=True).members.first()
        invitation = PrescriberWithOrgSentInvitationFactory(
            sender=self.sender,
            organization=self.organization,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )

        self.client.force_login(user)
        response = self.client.get(invitation.acceptance_link, follow=True)
        assert response.status_code == 403
        invitation.refresh_from_db()
        assert not invitation.accepted

    def test_connected_user_is_not_the_invited_user(self):
        invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.organization)
        self.client.force_login(self.sender)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertRedirects(response, reverse("account_logout"))
        invitation.refresh_from_db()
        assert not invitation.accepted
        self.assertContains(response, escape("Un utilisateur est déjà connecté."))

    def test_expired_invitation_with_new_user(self):
        invitation = PrescriberWithOrgSentInvitationFactory(sender=self.sender, organization=self.organization)
        invitation.sent_at -= timedelta(days=invitation.DEFAULT_VALIDITY_DAYS)
        invitation.save()
        assert invitation.has_expired

        post_data = {
            "first_name": invitation.first_name,
            "last_name": invitation.last_name,
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = self.client.post(invitation.acceptance_link, data=post_data, follow=True)
        self.assertContains(response, escape("Cette invitation n'est plus valide."))

    def test_expired_invitation_with_existing_user(self):
        user = PrescriberFactory()
        invitation = PrescriberWithOrgSentInvitationFactory(
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            sender=self.sender,
            organization=self.organization,
        )
        invitation.sent_at -= timedelta(days=invitation.DEFAULT_VALIDITY_DAYS)
        invitation.save()
        assert invitation.has_expired

        # GET or POST in this case
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertContains(response, escape("Cette invitation n'est plus valide."))

        self.client.force_login(user)
        # Try to bypass the first check by directly reaching the join endpoint
        join_url = reverse("invitations_views:join_prescriber_organization", kwargs={"invitation_id": invitation.id})
        response = self.client.get(join_url, follow=True)
        # The 2 views return the same error message
        self.assertContains(response, escape("Cette invitation n'est plus valide."))
