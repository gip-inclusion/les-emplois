from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.contrib import messages
from django.urls import reverse
from pytest_django.asserts import assertMessages, assertRedirects

from itou.users.enums import IdentityProvider
from itou.www.dashboard.forms import EditUserEmailForm
from tests.users.factories import (
    JobSeekerFactory,
    PrescriberFactory,
)


class TestChangeEmailView:
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

        post_data = {"email": new_email, "email_confirmation": new_email}
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
        assert email.to[0] == new_email

        # Confirm email : email is changed
        confirmation_token = EmailConfirmationHMAC(user.emailaddress_set.get(email=new_email)).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
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
        old_email = "bernard@blier.fr"

        # Email and confirmation email do not match
        email = "jean@gabin.fr"
        email_confirmation = "oscar@gabin.fr"
        data = {"email": email, "email_confirmation": email_confirmation}
        form = EditUserEmailForm(data=data, user_email=old_email)
        assert not form.is_valid()

        # Email already taken by another user. Bad luck!
        user = JobSeekerFactory()
        data = {"email": user.email, "email_confirmation": user.email}
        form = EditUserEmailForm(data=data, user_email=old_email)
        assert not form.is_valid()

        # New address is the same as the old one.
        data = {"email": old_email, "email_confirmation": old_email}
        form = EditUserEmailForm(data=data, user_email=old_email)
        assert not form.is_valid()

    def test_valid_form(self):
        old_email = "bernard@blier.fr"
        new_email = "jean@gabin.fr"
        data = {"email": new_email, "email_confirmation": new_email}
        form = EditUserEmailForm(data=data, user_email=old_email)
        assert form.is_valid()
