import random

import pytest
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

from itou.invitations.models import LaborInspectorInvitation
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.perms.institution import get_current_institution_or_404
from tests.institutions.factories import InstitutionFactory, InstitutionMembershipFactory
from tests.invitations.factories import LaborInspectorInvitationFactory
from tests.users.factories import (
    DEFAULT_PASSWORD,
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.test import assert_previous_step


INVITATION_URL = reverse("invitations_views:invite_labor_inspector")


class TestSendInstitutionInvitation:
    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.institution = InstitutionFactory()
        self.sender = InstitutionMembershipFactory(institution=self.institution).user
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
        invitation = LaborInspectorInvitation.objects.get(institution=self.institution)
        assert invitation.first_name == self.post_data["form-0-first_name"]
        assert invitation.last_name == self.post_data["form-0-last_name"]
        assert invitation.email == self.post_data["form-0-email"]
        assert invitation.institution == self.institution

    def test_invite_previous_step_link(self, client):
        response = client.get(INVITATION_URL)
        assert_previous_step(response, reverse("institutions_views:members"))

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

    def test_invite_existing_user(self, client):
        guest = LaborInspectorFactory()
        self.post_data["form-0-first_name"] = guest.first_name
        self.post_data["form-0-last_name"] = guest.last_name
        self.post_data["form-0-email"] = guest.email
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertRedirects(response, INVITATION_URL)
        self.assert_created_invitation()

    def test_invite_multiple_users(self, client):
        guest = LaborInspectorFactory.build()
        self.post_data["form-TOTAL_FORMS"] = "2"
        self.post_data["form-1-first_name"] = guest.first_name
        self.post_data["form-1-last_name"] = guest.last_name
        self.post_data["form-1-email"] = self.post_data["form-0-email"]
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertContains(
            response,
            escape("Les collaborateurs doivent avoir des adresses e-mail différentes."),
        )
        assert LaborInspectorInvitation.objects.count() == 0

        self.post_data["form-1-email"] = guest.email
        client.post(INVITATION_URL, data=self.post_data, follow=True)
        assert LaborInspectorInvitation.objects.count() == 2

    def test_invite_former_member(self, client):
        """
        Admins can "deactivate" members of the organization (making the membership inactive).
        A deactivated member must be able to receive new invitations.
        """
        # Invite user (part 1)
        guest = LaborInspectorFactory()
        self.post_data["form-0-first_name"] = guest.first_name
        self.post_data["form-0-last_name"] = guest.last_name
        self.post_data["form-0-email"] = guest.email
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertRedirects(response, INVITATION_URL)
        self.assert_created_invitation()

        # Deactivate user
        self.institution.members.add(guest)
        guest.save()
        membership = guest.institutionmembership_set.first()
        self.institution.deactivate_membership(membership, updated_by=self.institution.members.first())
        assert guest not in self.institution.active_members
        # Invite user (the revenge)
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertRedirects(response, INVITATION_URL)
        assert LaborInspectorInvitation.objects.filter(institution=self.institution).count() == 2

    def test_two_institutions_invite_the_same_guest(self, client):
        # institution 1 invites guest.
        client.post(INVITATION_URL, data=self.post_data, follow=True)
        assert LaborInspectorInvitation.objects.count() == 1

        # institution 2 invites guest as well.
        institution_2 = InstitutionFactory()
        sender_2 = InstitutionMembershipFactory(institution=institution_2).user
        client.force_login(sender_2)
        client.post(INVITATION_URL, data=self.post_data)
        assert LaborInspectorInvitation.objects.count() == 2
        invitation = LaborInspectorInvitation.objects.get(institution=institution_2)
        assert invitation.first_name == self.guest_data["first_name"]
        assert invitation.last_name == self.guest_data["last_name"]
        assert invitation.email == self.guest_data["email"]


class TestSendInstitutionInvitationExceptions:
    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.institution = InstitutionFactory()
        self.sender = InstitutionMembershipFactory(institution=self.institution).user
        client.force_login(self.sender)

    def assert_invalid_user(self, response, reason):
        assert not response.context["formset"].is_valid()
        assert response.context["formset"].errors[0]["email"][0] == reason
        assert not LaborInspectorInvitation.objects.exists()

    def test_invite_existing_user_is_bad_kind(self, client):
        guest = random.choice([JobSeekerFactory, EmployerFactory, PrescriberFactory, ItouStaffFactory])()
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
        self.assert_invalid_user(response, "Cet utilisateur n'est pas un inspecteur du travail.")

    def test_already_a_member(self, client):
        # The invited user is already a member
        guest = LaborInspectorFactory()
        self.institution.members.add(guest)
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
        self.assert_invalid_user(response, "Cette personne fait déjà partie de votre structure.")


class TestAcceptInstitutionInvitation:
    def assert_invitation_is_accepted(self, response, user, invitation, mailoutbox):
        user.refresh_from_db()
        invitation.refresh_from_db()
        assert user.kind == UserKind.LABOR_INSPECTOR

        assert invitation.accepted_at
        assert invitation.institution.members.count() == 2

        # Make sure there's a welcome message.
        assertContains(
            response, escape(f"Vous êtes désormais membre de l'organisation {invitation.institution.display_name}.")
        )
        assertNotContains(response, escape("Ce lien n'est plus valide."))

        # A confirmation e-mail is sent to the invitation sender.
        assert len(mailoutbox) == 1
        assert len(mailoutbox[0].to) == 1
        assert invitation.sender.email == mailoutbox[0].to[0]

        # Assert the user sees his new organization dashboard.
        current_institution = get_current_institution_or_404(response.wsgi_request)
        # A user can be member of one or more organizations
        assert current_institution in user.institution_set.all()

    def test_accept_invitation_new_user(self, client, mailoutbox):
        invitation = LaborInspectorInvitationFactory()
        form_data = {
            "first_name": "Joe",
            "last_name": "Dalton",
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = client.post(invitation.acceptance_link, data=form_data, follow=True)
        assertRedirects(response, reverse("dashboard:index"))

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_accept_existing_user(self, client, mailoutbox):
        user = LaborInspectorFactory()
        invitation = LaborInspectorInvitationFactory(email=user.email)
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
        # /invitations/<uuid>/join_institution then /dashboard
        assert len(response.redirect_chain) == 2
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_accept_existing_user_email_different_case(self, client, mailoutbox):
        user = LaborInspectorFactory()
        invitation = LaborInspectorInvitationFactory(email=user.email.upper())
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_accept_existing_user_belongs_to_another_organization(self, client, mailoutbox):
        user = InstitutionMembershipFactory().user
        invitation = LaborInspectorInvitationFactory(email=user.email)
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)
        assert user.institution_set.count() == 2

    def test_auto_accept_invitation_on_login(self, client, mailoutbox):
        # The user's invitations are automatically accepted at login
        user = LaborInspectorFactory(with_verified_email=True)
        invitation = LaborInspectorInvitationFactory(email=user.email)

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(reverse("login:labor_inspector"), data=form_data)
        assertRedirects(response, reverse("welcoming_tour:index"), fetch_redirect_response=False)
        response = client.get(response.url)

        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_accept_existing_user_not_logged_in(self, client, mailoutbox):
        user = LaborInspectorFactory(with_verified_email=True)
        invitation = LaborInspectorInvitationFactory(email=user.email)
        response = client.get(invitation.acceptance_link, follow=True)
        assert reverse("login:labor_inspector") in response.wsgi_request.get_full_path()
        assert not invitation.accepted_at

        response = client.post(
            response.wsgi_request.get_full_path(),
            data={"login": user.email, "password": DEFAULT_PASSWORD},
            follow=True,
        )
        assert response.context["user"].is_authenticated
        assertRedirects(response, reverse("dashboard:index"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)


class TestAcceptInstitutionInvitationException:
    def test_existing_user_is_bad_kind(self, client):
        user = random.choice([JobSeekerFactory, EmployerFactory, PrescriberFactory, ItouStaffFactory])()
        invitation = LaborInspectorInvitationFactory(email=user.email)

        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assert response.status_code == 403
        invitation.refresh_from_db()
        assert not invitation.accepted_at

    def test_connected_user_is_not_the_invited_user(self, client):
        invitation = LaborInspectorInvitationFactory()
        client.force_login(LaborInspectorFactory(membership=True))
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("account_logout"))
        invitation.refresh_from_db()
        assert not invitation.accepted_at
        assertContains(response, escape("Un utilisateur est déjà connecté."))

    def test_expired_invitation_with_new_user(self, client):
        invitation = LaborInspectorInvitationFactory(expired=True)

        # User wants to join our website but it's too late!
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, escape("Lien d'activation expiré"), html=True)
        assertContains(response, escape("Ce lien n'est plus valide."))

    def test_expired_invitation_with_existing_user(self, client):
        user = LaborInspectorFactory()
        invitation = LaborInspectorInvitationFactory(expired=True, email=user.email)

        # GET or POST in this case
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, escape("Ce lien n'est plus valide."))

        client.force_login(user)
        # Try to bypass the first check by directly reaching the join endpoint
        join_url = reverse("invitations_views:join_institution", kwargs={"invitation_id": invitation.id})
        response = client.get(join_url, follow=True)
        # The 2 views return the same error message
        assertContains(response, escape("Ce lien n'est plus valide."))

    def test_non_existent_invitation(self, client):
        invitation = LaborInspectorInvitationFactory(
            first_name="Léonie", last_name="Bathiat", email="leonie@bathiat.com"
        )
        url = invitation.acceptance_link
        invitation.delete()
        response = client.get(url, follow=True)
        assert response.status_code == 404

    def test_accepted_invitation(self, client):
        invitation = LaborInspectorInvitationFactory(accepted=True)
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, escape("Lien d'activation déjà accepté"), html=True)
