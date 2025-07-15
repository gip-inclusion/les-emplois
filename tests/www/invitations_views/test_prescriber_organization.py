import random
from urllib.parse import urlencode

import pytest
import respx
from django.conf import settings
from django.contrib import messages
from django.shortcuts import reverse
from django.utils.html import escape
from freezegun import freeze_time
from pytest_django.asserts import (
    assertContains,
    assertMessages,
    assertNotContains,
    assertRedirects,
)

from itou.invitations.models import PrescriberWithOrgInvitation
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.urls import add_url_params
from tests.invitations.factories import PrescriberWithOrgInvitationFactory
from tests.prescribers.factories import (
    PrescriberMembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
    PrescriberPoleEmploiFactory,
)
from tests.users.factories import (
    DEFAULT_PASSWORD,
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.test import ItouClient, assert_previous_step


INVITATION_URL = reverse("invitations_views:invite_prescriber_with_org")


class TestSendPrescriberWithOrgInvitation:
    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.organization = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganizationKind.CAP_EMPLOI)
        self.sender = self.organization.members.first()
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
        client.force_login(self.sender)

    def assert_created_invitation(self):
        invitation = PrescriberWithOrgInvitation.objects.get(organization=self.organization)
        assert invitation.first_name == self.post_data["form-0-first_name"]
        assert invitation.last_name == self.post_data["form-0-last_name"]
        assert invitation.email == self.post_data["form-0-email"]
        assert invitation.organization == self.organization

    def test_invite_previous_step_link(self, client):
        response = client.get(INVITATION_URL)
        assert_previous_step(response, reverse("prescribers_views:members"))

    @freeze_time("2025-04-10")
    def test_invite_not_existing_user(self, client, mailoutbox):
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertRedirects(response, INVITATION_URL)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.SUCCESS,
                    (
                        "Collaborateur ajouté||Pour rejoindre votre organisation, il suffira à votre collaborateur "
                        "de cliquer sur le lien d'activation contenu dans l'e-mail avant le 24 avril 2025."
                    ),
                    extra_tags="toast",
                ),
            ],
        )
        self.assert_created_invitation()

        # Make sure an email has been sent to the invited person
        outbox_emails = [receiver for message in mailoutbox for receiver in message.to]
        assert self.post_data["form-0-email"] in outbox_emails

    def test_invite_multiple_users(self, client):
        guest = PrescriberFactory.build()
        self.post_data["form-TOTAL_FORMS"] = "2"
        self.post_data["form-1-first_name"] = guest.first_name
        self.post_data["form-1-last_name"] = guest.last_name
        self.post_data["form-1-email"] = self.post_data["form-0-email"]
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertContains(
            response,
            escape("Les collaborateurs doivent avoir des adresses e-mail différentes."),
        )
        assert PrescriberWithOrgInvitation.objects.count() == 0

        self.post_data["form-1-email"] = guest.email
        client.post(INVITATION_URL, data=self.post_data, follow=True)
        assert PrescriberWithOrgInvitation.objects.count() == 2

    def test_invite_not_existing_user_with_prefill(self, client):
        response = client.get(
            INVITATION_URL, data={"first_name": "Emma", "last_name": "Watson", "email": "emma@example.com"}
        )
        # The form is prefilled with GET params (if valid)
        assertContains(response, "Emma")

    def test_invite_existing_user(self, client):
        guest = PrescriberFactory()
        self.post_data["form-0-first_name"] = guest.first_name
        self.post_data["form-0-last_name"] = guest.last_name
        self.post_data["form-0-email"] = guest.email
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertRedirects(response, INVITATION_URL)
        self.assert_created_invitation()

    def test_invite_former_member(self, client):
        """
        Admins can "deactivate" members of the organization (making the membership inactive).
        A deactivated member must be able to receive new invitations.
        """
        # Invite user (part 1)
        guest = PrescriberFactory()
        self.post_data["form-0-first_name"] = guest.first_name
        self.post_data["form-0-last_name"] = guest.last_name
        self.post_data["form-0-email"] = guest.email
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertRedirects(response, INVITATION_URL)
        self.assert_created_invitation()

        # Deactivate user
        self.organization.members.add(guest)
        guest.save()
        membership = guest.prescribermembership_set.first()
        self.organization.deactivate_membership(membership, updated_by=self.organization.members.first())
        assert guest not in self.organization.active_members
        # Invite user (the revenge)
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertRedirects(response, INVITATION_URL)
        assert PrescriberWithOrgInvitation.objects.filter(organization=self.organization).count() == 2

    def test_two_prescribers_invite_the_same_guest(self, client):
        # organization 1 invites guest.
        client.post(INVITATION_URL, data=self.post_data, follow=True)
        assert PrescriberWithOrgInvitation.objects.count() == 1

        # organization 2 invites guest as well.
        organization_2 = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganizationKind.CAP_EMPLOI)
        sender_2 = organization_2.members.first()
        client.force_login(sender_2)
        client.post(INVITATION_URL, data=self.post_data)
        assert PrescriberWithOrgInvitation.objects.count() == 2
        invitation = PrescriberWithOrgInvitation.objects.get(organization=organization_2)
        assert invitation.first_name == self.guest_data["first_name"]
        assert invitation.last_name == self.guest_data["last_name"]
        assert invitation.email == self.guest_data["email"]


class TestSendPrescriberWithOrgInvitationExceptions:
    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.organization = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganizationKind.CAP_EMPLOI)
        self.sender = self.organization.members.first()
        client.force_login(self.sender)

    def assert_invalid_user(self, response, reason):
        assert not response.context["formset"].is_valid()
        assert response.context["formset"].errors[0]["email"][0] == reason
        assert not PrescriberWithOrgInvitation.objects.exists()

    def test_invite_existing_user_is_bad_kind(self, client):
        guest = random.choice([JobSeekerFactory, EmployerFactory, LaborInspectorFactory, ItouStaffFactory])()
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": guest.first_name,
            "form-0-last_name": guest.last_name,
            "form-0-email": guest.email,
        }

        response = client.post(INVITATION_URL, data=post_data)
        assert response.status_code == 200
        self.assert_invalid_user(response, "Cet utilisateur n'est pas un prescripteur.")

    def test_already_a_member(self, client):
        # The invited user is already a member
        self.organization.members.add(PrescriberFactory())
        guest = self.organization.members.exclude(email=self.sender.email).first()
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": guest.first_name,
            "form-0-last_name": guest.last_name,
            "form-0-email": guest.email,
        }
        response = client.post(INVITATION_URL, data=post_data)
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
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
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
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
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


class TestAcceptPrescriberWithOrgInvitation:
    def assert_invitation_is_accepted(self, response, user, invitation, mailoutbox):
        user.refresh_from_db()
        invitation.refresh_from_db()
        assert user.kind == UserKind.PRESCRIBER

        assert invitation.accepted_at
        assert invitation.organization.members.count() == 2

        # Make sure there's a welcome message.
        assertContains(
            response, escape(f"Vous êtes désormais membre de l'organisation {invitation.organization.display_name}.")
        )
        assertNotContains(response, escape("Ce lien n'est plus valide."))

        # A confirmation e-mail is sent to the invitation sender.
        assert len(mailoutbox) == 1
        assert len(mailoutbox[0].to) == 1
        assert invitation.sender.email == mailoutbox[0].to[0]

        # Assert the user sees his new organization dashboard.
        current_org = get_current_org_or_404(response.wsgi_request)
        # A user can be member of one or more organizations
        assert current_org in user.prescriberorganization_set.all()

    @respx.mock
    def test_accept_new_user(self, client, mailoutbox, pro_connect):
        invitation = PrescriberWithOrgInvitationFactory(email=pro_connect.oidc_userinfo["email"])
        response = client.get(invitation.acceptance_link)
        pro_connect.assertContainsButton(response)

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
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        response = client.get(response.url, follow=True)
        assertRedirects(response, reverse("welcoming_tour:index"))

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    @respx.mock
    def test_accept_new_user_returns_on_other_browser(self, client, mailoutbox, pro_connect):
        invitation = PrescriberWithOrgInvitationFactory(email=pro_connect.oidc_userinfo["email"])
        response = client.get(invitation.acceptance_link)
        pro_connect.assertContainsButton(response)

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
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        other_client = ItouClient()
        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
            other_client=other_client,
        )
        response = other_client.get(response.url, follow=True)
        assertRedirects(response, reverse("welcoming_tour:index"))

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    @respx.mock
    def test_auto_accept_invitation_on_ProConnect_login(self, client, mailoutbox, pro_connect):
        # The user's invitations are automatically accepted at login
        invitation = PrescriberWithOrgInvitationFactory(email=pro_connect.oidc_userinfo["email"])

        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            user_email=invitation.email,
        )
        assertRedirects(response, reverse("welcoming_tour:index"), fetch_redirect_response=False)
        response = client.get(response.url)

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_auto_accept_invitation_on_django_login(self, client, mailoutbox, settings):
        settings.FORCE_PROCONNECT_LOGIN = False
        # The user's invitations are automatically accepted at login
        user = PrescriberFactory(with_verified_email=True)
        invitation = PrescriberWithOrgInvitationFactory(email=user.email)

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(reverse("login:prescriber"), data=form_data)
        assertRedirects(response, reverse("welcoming_tour:index"), fetch_redirect_response=False)
        response = client.get(response.url)

        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_accept_existing_user(self, client, mailoutbox):
        user = PrescriberFactory(has_completed_welcoming_tour=True)
        invitation = PrescriberWithOrgInvitationFactory(email=user.email)
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
        # /invitations/<uuid>/join_prescriber_with_org then /dashboard
        assert len(response.redirect_chain) == 2
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_accept_existing_user_different_email_case(self, client, mailoutbox):
        user = PrescriberFactory(has_completed_welcoming_tour=True)
        invitation = PrescriberWithOrgInvitationFactory(email=user.email.upper())
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_accept_existing_user_belongs_to_another_organization(self, client, mailoutbox):
        user = PrescriberMembershipFactory(user__has_completed_welcoming_tour=True).user
        invitation = PrescriberWithOrgInvitationFactory(email=user.email)
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)
        assert user.prescriberorganization_set.count() == 2

    @respx.mock
    def test_accept_existing_user_not_logged_in_using_ProConnect(self, client, mailoutbox, pro_connect):
        invitation = PrescriberWithOrgInvitationFactory(email=pro_connect.oidc_userinfo["email"])
        user = PrescriberFactory(
            username=pro_connect.oidc_userinfo["sub"],
            email=pro_connect.oidc_userinfo["email"],
            has_completed_welcoming_tour=True,
        )
        response = client.get(invitation.acceptance_link, follow=True)
        assert reverse("login:prescriber") in response.wsgi_request.get_full_path()
        assert not invitation.accepted_at
        next_url = reverse("invitations_views:join_prescriber_organization", args=(invitation.pk,))
        previous_url = f"{reverse('login:prescriber')}?{urlencode({'next': next_url})}"
        params = {
            "user_kind": UserKind.PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            user_email=user.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        response = client.get(response.url, follow=True)
        assertRedirects(response, reverse("dashboard:index"))

        assert response.context["user"].is_authenticated
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_accept_existing_user_not_logged_in_using_django_auth(self, client, mailoutbox):
        user = PrescriberFactory(
            has_completed_welcoming_tour=True, identity_provider="DJANGO", with_verified_email=True
        )
        invitation = PrescriberWithOrgInvitationFactory(email=user.email)
        response = client.get(invitation.acceptance_link, follow=True)
        assert reverse("login:prescriber") in response.wsgi_request.get_full_path()
        assert not invitation.accepted_at

        response = client.post(
            response.wsgi_request.get_full_path(),
            data={"login": user.email, "password": DEFAULT_PASSWORD},
            follow=True,
        )
        assert response.context["user"].is_authenticated
        assertRedirects(response, reverse("dashboard:activate_pro_connect_account"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)


class TestAcceptPrescriberWithOrgInvitationExceptions:
    def test_existing_user_is_bad_kind(self, client):
        user = random.choice([JobSeekerFactory, EmployerFactory, LaborInspectorFactory, ItouStaffFactory])()
        invitation = PrescriberWithOrgInvitationFactory(email=user.email)

        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assert response.status_code == 403
        invitation.refresh_from_db()
        assert not invitation.accepted_at

    def test_connected_user_is_not_the_invited_user(self, client):
        invitation = PrescriberWithOrgInvitationFactory()
        client.force_login(PrescriberFactory())
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("account_logout"))
        invitation.refresh_from_db()
        assert not invitation.accepted_at
        assertContains(response, escape("Un utilisateur est déjà connecté."))

    @respx.mock
    def test_accept_invitation_signup_wrong_email(self, client, pro_connect):
        invitation = PrescriberWithOrgInvitationFactory()
        response = client.get(invitation.acceptance_link)
        pro_connect.assertContainsButton(response)

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
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        # Singup fails on ProConnet with email different than the one from the invitation
        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.PRESCRIBER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
            expected_redirect_url=add_url_params(pro_connect.logout_url, {"redirect_url": previous_url}),
        )
        # ProConnect redirects to previous_url
        response = client.get(previous_url, follow=True)
        # Signup should have failed : as the email used in IC isn't the one from the invitation
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "L’adresse e-mail que vous avez utilisée pour vous connecter avec "
                    f"{pro_connect.identity_provider.label} (michel@lestontons.fr) ne correspond pas à "
                    f"l’adresse e-mail de l’invitation ({invitation.email}).",
                )
            ],
        )
        assert not User.objects.filter(email=invitation.email).exists()

    def test_expired_invitation_with_new_user(self, client):
        invitation = PrescriberWithOrgInvitationFactory(expired=True)

        # User wants to join our website but it's too late!
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, escape("Lien d'activation expiré"), html=True)
        assertContains(response, escape("Ce lien n'est plus valide."))

    def test_expired_invitation_with_existing_user(self, client):
        user = PrescriberFactory()
        invitation = PrescriberWithOrgInvitationFactory(email=user.email, expired=True)

        # GET or POST in this case
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, escape("Ce lien n'est plus valide."))

        client.force_login(user)
        # Try to bypass the first check by directly reaching the join endpoint
        join_url = reverse("invitations_views:join_prescriber_organization", kwargs={"invitation_id": invitation.id})
        response = client.get(join_url, follow=True)
        # The 2 views return the same error message
        assertContains(response, escape("Ce lien n'est plus valide."))

    def test_non_existent_invitation(self, client):
        invitation = PrescriberWithOrgInvitationFactory(
            first_name="Léonie", last_name="Bathiat", email="leonie@bathiat.com"
        )
        url = invitation.acceptance_link
        invitation.delete()
        response = client.get(url, follow=True)
        assert response.status_code == 404

    def test_accepted_invitation(self, client):
        invitation = PrescriberWithOrgInvitationFactory(accepted=True)
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, escape("Lien d'activation déjà accepté"), html=True)
