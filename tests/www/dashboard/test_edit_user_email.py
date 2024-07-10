from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.core import mail
from django.urls import reverse

from itou.users.enums import IdentityProvider
from itou.www.dashboard.forms import EditUserEmailForm
from tests.users.factories import (
    DEFAULT_PASSWORD,
    JobSeekerFactory,
    PrescriberFactory,
)
from tests.utils.test import TestCase


class ChangeEmailViewTest(TestCase):
    def test_update_email(self):
        user = JobSeekerFactory()
        old_email = user.email
        new_email = "jean@gabin.fr"

        self.client.force_login(user)
        url = reverse("dashboard:edit_user_email")
        response = self.client.get(url)

        email_address = EmailAddress(email=old_email, verified=True, primary=True)
        email_address.user = user
        email_address.save()

        post_data = {"email": new_email, "email_confirmation": new_email}
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        # User is logged out
        user.refresh_from_db()
        assert response.request.get("user") is None
        assert user.email == new_email
        assert user.emailaddress_set.count() == 0

        # User cannot log in with his old address
        post_data = {"login": old_email, "password": DEFAULT_PASSWORD}
        url = reverse("login:job_seeker")
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        assert not response.context_data["form"].is_valid()

        # User cannot log in until confirmation
        post_data = {"login": new_email, "password": DEFAULT_PASSWORD}
        url = reverse("login:job_seeker")
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        assert response.url == reverse("account_email_verification_sent")

        # User receives an email to confirm his new address.
        email = mail.outbox[0]
        assert "Confirmez votre adresse e-mail" in email.subject
        assert "Afin de finaliser votre inscription, cliquez sur le lien suivant" in email.body
        assert email.to[0] == new_email

        # Confirm email + auto login.
        confirmation_token = EmailConfirmationHMAC(user.emailaddress_set.first()).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        response = self.client.post(confirm_email_url)
        assert response.status_code == 302
        assert response.url == reverse("account_login")

        post_data = {"login": user.email, "password": DEFAULT_PASSWORD}
        url = reverse("account_login")
        response = self.client.post(url, data=post_data)
        assert response.context.get("user").is_authenticated

        user.refresh_from_db()
        assert user.email == new_email
        assert user.emailaddress_set.count() == 1
        new_address = user.emailaddress_set.first()
        assert new_address.email == new_email
        assert new_address.verified

    def test_update_email_forbidden(self):
        url = reverse("dashboard:edit_user_email")

        job_seeker = JobSeekerFactory(identity_provider=IdentityProvider.FRANCE_CONNECT)
        self.client.force_login(job_seeker)
        response = self.client.get(url)
        assert response.status_code == 403

        prescriber = PrescriberFactory(identity_provider=IdentityProvider.INCLUSION_CONNECT)
        self.client.force_login(prescriber)
        response = self.client.get(url)
        assert response.status_code == 403


class EditUserEmailFormTest(TestCase):
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
