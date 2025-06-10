from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.contrib import messages
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertMessages, assertRedirects

from itou.users.enums import IdentityProvider
from itou.www.dashboard.forms import EditUserEmailForm
from tests.users.factories import (
    DEFAULT_PASSWORD,
    JobSeekerFactory,
    PrescriberFactory,
)


class TestChangeEmailView:
    @freeze_time()  # the email confirmation token depends on the time
    def test_update_email(self, client, mailoutbox):
        user = JobSeekerFactory(email="ancien@email.fr")
        old_email = user.email
        new_email = "jean@gabin.fr"

        client.force_login(user)
        url = reverse("dashboard:edit_user_email")
        response = client.get(url)

        email_address = EmailAddress(email=old_email, verified=True, primary=True)
        email_address.user = user
        email_address.save()

        post_data = {"email": new_email, "email_confirmation": new_email, "password": DEFAULT_PASSWORD}
        response = client.post(url, data=post_data)
        assertRedirects(
            response,
            reverse("dashboard:index"),
            # The user is then redirected to edit_user_info but we don't care about that
            fetch_redirect_response=False,
        )
        assertMessages(
            response,
            [messages.Message(messages.INFO, "E-mail de confirmation envoyé à jean@gabin.fr")],
        )
        user.refresh_from_db()
        assert user.email == old_email
        assert sorted(EmailAddress.objects.values_list("email", "verified", "primary", "user")) == [
            (old_email, True, True, user.pk),
            (new_email, False, False, user.pk),
        ]

        # User receives an email to confirm his new address.
        email = mailoutbox[0]
        assert "Confirmez votre adresse e-mail" in email.subject
        assert "Nous avons bien enregistré votre demande de modification d'adresse e-mail." in email.body
        assert "Afin de finaliser ce changement, cliquez sur le lien suivant" in email.body
        assert email.to == [new_email]
        confirmation_token = EmailConfirmationHMAC(user.emailaddress_set.get(email=new_email)).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        assert confirm_email_url in email.body

        # Confirm email : email is changed
        response = client.post(confirm_email_url)
        assert response.status_code == 302
        assert response.url == reverse("welcoming_tour:index")
        response = client.get(response.url)
        assert response.context.get("user").is_authenticated

        user.refresh_from_db()
        assert user.email == new_email
        assert user.emailaddress_set.count() == 1
        new_address = user.emailaddress_set.first()
        assert new_address.email == new_email
        assert new_address.verified

    def test_update_email_forbidden(self, client):
        url = reverse("dashboard:edit_user_email")

        job_seeker = JobSeekerFactory(identity_provider=IdentityProvider.FRANCE_CONNECT)
        client.force_login(job_seeker)
        response = client.get(url)
        assert response.status_code == 403

        prescriber = PrescriberFactory()
        client.force_login(prescriber)
        response = client.get(url)
        assert response.status_code == 403


class TestEditUserEmailForm:
    def test_invalid_form(self):
        user = JobSeekerFactory()

        # Email and confirmation email do not match
        email = "jean@gabin.fr"
        email_confirmation = "oscar@gabin.fr"
        data = {"email": email, "email_confirmation": email_confirmation, "password": DEFAULT_PASSWORD}
        form = EditUserEmailForm(user, data=data)
        assert not form.is_valid()

        # Email already taken by another user. Bad luck!
        other_user = JobSeekerFactory()
        data = {"email": other_user.email, "email_confirmation": other_user.email, "password": DEFAULT_PASSWORD}
        form = EditUserEmailForm(user, data=data)
        assert not form.is_valid()

        # New address is the same as the old one.
        data = {"email": user.email, "email_confirmation": user.email, "password": DEFAULT_PASSWORD}
        form = EditUserEmailForm(user, data=data)
        assert not form.is_valid()

        # password is wrong
        data = {"email": email, "email_confirmation": email, "password": "bad_password"}
        form = EditUserEmailForm(user, data=data)
        assert not form.is_valid()

    def test_valid_form(self):
        user = JobSeekerFactory()
        new_email = "jean@gabin.fr"
        data = {"email": new_email, "email_confirmation": new_email, "password": DEFAULT_PASSWORD}
        form = EditUserEmailForm(user, data=data)
        assert form.is_valid()
