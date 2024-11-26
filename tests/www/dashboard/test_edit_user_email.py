import re

from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.urls import reverse
from pytest_django.asserts import assertRedirects

from itou.users.enums import IdentityProvider
from itou.www.dashboard.forms import EditUserEmailForm
from tests.users.factories import (
    DEFAULT_PASSWORD,
    JobSeekerFactory,
    PrescriberFactory,
)


class TestChangeEmailView:
    def test_update_email(self, client, mailoutbox, snapshot):
        user = JobSeekerFactory(with_verified_email=True)
        old_email = user.email
        new_email = "jean@gabin.fr"

        client.force_login(user)
        url = reverse("dashboard:edit_user_email")
        response = client.get(url)

        post_data = {"email": new_email, "email_confirmation": new_email}
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

        # User receives an email to confirm their new address.
        email = mailoutbox[0]
        assert "Confirmez votre adresse e-mail" in email.subject
        assert email.to[0] == new_email

        # Test email contents against a snapshot (remove key which changes)
        confirmation_link = reverse(
            "account_confirm_email",
            kwargs={"key": "key123"},
        )

        # http://localhost:8000/accounts/confirm-email/(?P<key>[-:\w]+)/
        pattern = re.sub("key123/", r"([-:\\w]+)/", confirmation_link)
        confirmation_link = re.search(pattern, email.body)[0]

        # Test the email content is valid
        assert re.sub(pattern, "[CONFIRM EMAIL LINK REMOVED]", email.body) == snapshot

        # User is logged out
        user.refresh_from_db()
        assert response.request.get("user") is None

        # Email is not updated until the user confirms it
        assert user.email == old_email
        assert user.emailaddress_set.count() == 2
        assert EmailAddress.objects.filter(email=new_email, verified=False, primary=False, user=user).exists()

        # User cannot log in with the new address until confirmation
        post_data = {"login": new_email, "password": DEFAULT_PASSWORD}
        url = reverse("login:job_seeker")
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

        # Confirm email + auto login.
        confirmation_token = EmailConfirmationHMAC(user.emailaddress_set.filter(email=new_email).first()).key
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
        assert new_address.primary

        # Old email address has been liberated
        assert not EmailAddress.objects.filter(email=old_email).exists()

    def test_update_email_can_login_while_pending(self, client, mailoutbox):
        # User has an email modification ongoing
        user = JobSeekerFactory(with_verified_email=True)
        old_email = user.email
        new_email = "jean@gabin.fr"

        email_address = EmailAddress(email=new_email, verified=False)
        email_address.user = user
        email_address.save()

        # They can login with their old email while pending verification
        post_data = {"login": old_email, "password": DEFAULT_PASSWORD}
        url = reverse("login:job_seeker")
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("welcoming_tour:index"))

        user.refresh_from_db()
        assert user.email == old_email
        assert user.emailaddress_set.count() == 2

    def test_user_cannot_reserve_many_emails(self, client):
        user = JobSeekerFactory(with_verified_email=True)
        first_email = user.email
        second_email = "jean@gabin.fr"
        client.force_login(user)

        email_address = EmailAddress(email=second_email, verified=False)
        email_address.user = user
        email_address.save()
        confirmation_token = EmailConfirmationHMAC(email_address).key

        third_email = "marc@gabin.fr"
        post_data = {"email": third_email, "email_confirmation": third_email}
        response = client.post(reverse("dashboard:edit_user_email"), data=post_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

        # The previous email modification request is replaced
        assert EmailAddress.objects.filter(user=user, email=first_email, verified=True, primary=True).exists()
        assert not EmailAddress.objects.filter(email=second_email).exists()
        assert EmailAddress.objects.filter(user=user, email=third_email, verified=False).exists()

        # Cannot now verify the older email
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        response = client.post(confirm_email_url)
        assert response.status_code == 404

    def test_update_email_conflict(self, client):
        # Another user has already reserved an email address
        other_user = JobSeekerFactory(with_verified_email=True)
        email_address = EmailAddress(email="paul@gabin.fr", verified=False)
        email_address.user = other_user
        email_address.save()

        url = reverse("dashboard:edit_user_email")

        # Another user cannot attempt to use this email address
        user = JobSeekerFactory(with_verified_email=True)
        client.force_login(user)
        post_data = {"email": email_address.email, "email_confirmation": email_address.email}
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors["email"] == [
            "Cette adresse est déjà utilisée par un autre utilisateur."
        ]

        # Email addresses are not case sensitive (RFC 5321 Part 2.4)
        post_data = {"email": email_address.email.upper(), "email_confirmation": email_address.email.upper()}
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors["email"] == [
            "Cette adresse est déjà utilisée par un autre utilisateur."
        ]

        # Nor can I request my own email address
        post_data = {"email": user.email, "email_confirmation": user.email}
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors["email"] == ["Veuillez indiquer une adresse différente de l'actuelle."]

        # No error message if it's an email which I requested earlier (and presumably forgot)
        email_address.user = user
        email_address.save()
        post_data = {"email": email_address.email, "email_confirmation": email_address.email}
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("account_email_verification_sent"))
        assert EmailAddress.objects.filter(email=email_address.email).count() == 1

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
        existing_user = JobSeekerFactory(with_verified_email=True)

        # Email and confirmation email do not match
        email = "jean@gabin.fr"
        email_confirmation = "oscar@gabin.fr"
        data = {"email": email, "email_confirmation": email_confirmation}
        form = EditUserEmailForm(data=data, user=existing_user)
        assert not form.is_valid()

        # Email already taken by another user. Bad luck!
        user = JobSeekerFactory()
        data = {"email": user.email, "email_confirmation": user.email}
        form = EditUserEmailForm(data=data, user=existing_user)
        assert not form.is_valid()

        # New address is the same as the old one.
        data = {"email": existing_user.email, "email_confirmation": existing_user.email}
        form = EditUserEmailForm(data=data, user=existing_user)
        assert not form.is_valid()

    def test_valid_form(self):
        existing_user = JobSeekerFactory(with_verified_email=True)
        new_email = "jean@gabin.fr"
        data = {"email": new_email, "email_confirmation": new_email}
        form = EditUserEmailForm(data=data, user=existing_user)
        assert form.is_valid()
