from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import gettext as _

from itou.siaes.factories import (
    SiaeAfterGracePeriodFactory,
    SiaeFactory,
    SiaePendingGracePeriodFactory,
    SiaeWithMembershipFactory,
)
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, SiaeStaffFactory
from itou.www.dashboard.forms import EditUserEmailForm


class DashboardViewTest(TestCase):
    def test_dashboard(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_user_with_inactive_siae_can_still_login_during_grace_period(self):
        siae = SiaePendingGracePeriodFactory()
        user = SiaeStaffFactory()
        siae.members.add(user)
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_user_with_inactive_siae_cannot_login_after_grace_period(self):
        siae = SiaeAfterGracePeriodFactory()
        user = SiaeStaffFactory()
        siae.members.add(user)
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("dashboard:index")
        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 200)
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(last_url, reverse("account_logout"))

        expected_message = _("votre compte n'est malheureusement plus actif")
        self.assertContains(response, expected_message)


class EditUserInfoViewTest(TestCase):
    def test_edit(self):
        user = JobSeekerFactory()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = get_user_model().objects.get(id=user.id)
        self.assertEqual(user.phone, post_data["phone"])
        self.assertEqual(user.birthdate.strftime("%d/%m/%Y"), post_data["birthdate"])


class ChangeEmailViewTest(TestCase):
    def test_update_email(self):
        user = JobSeekerFactory()
        old_email = user.email
        new_email = "jean@gabin.fr"

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:edit_user_email")
        response = self.client.get(url)

        email_address = EmailAddress(email=old_email, verified=True, primary=True)
        email_address.user = user
        email_address.save()

        post_data = {"email": new_email, "email_confirmation": new_email}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        # User is logged out
        user.refresh_from_db()
        self.assertEqual(response.request.get("user"), None)
        self.assertEqual(user.email, new_email)
        self.assertEqual(user.emailaddress_set.count(), 0)

        # User cannot log in with his old address
        post_data = {"login": old_email, "password": DEFAULT_PASSWORD}
        url = reverse("account_login")
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context_data["form"].is_valid())

        # User cannot log in until confirmation
        post_data = {"login": new_email, "password": DEFAULT_PASSWORD}
        url = reverse("account_login")
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("account_email_verification_sent"))

        # User receives an email to confirm his new address.
        email = mail.outbox[0]
        self.assertIn("Confirmez votre adresse e-mail pour la Plateforme", email.subject)
        self.assertIn("Afin de finaliser votre inscription, cliquez sur le lien suivant", email.body)
        self.assertEqual(email.to[0], new_email)

        # Confirm email + auto login.
        confirmation_token = EmailConfirmationHMAC(user.emailaddress_set.first()).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        response = self.client.post(confirm_email_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("account_login"))

        post_data = {"login": user.email, "password": DEFAULT_PASSWORD}
        url = reverse("account_login")
        response = self.client.post(url, data=post_data)
        self.assertTrue(response.context.get("user").is_authenticated)

        user.refresh_from_db()
        self.assertEqual(user.email, new_email)
        self.assertEqual(user.emailaddress_set.count(), 1)
        new_address = user.emailaddress_set.first()
        self.assertEqual(new_address.email, new_email)
        self.assertTrue(new_address.verified)


class EditUserEmailFormTest(TestCase):
    def test_invalid_form(self):
        old_email = "bernard@blier.fr"

        # Email and confirmation email do not match
        email = "jean@gabin.fr"
        email_confirmation = "oscar@gabin.fr"
        data = {"email": email, "email_confirmation": email_confirmation}
        form = EditUserEmailForm(data=data, user_email=old_email)
        self.assertFalse(form.is_valid())

        # Email already taken by another user. Bad luck!
        user = JobSeekerFactory()
        data = {"email": user.email, "email_confirmation": user.email}
        form = EditUserEmailForm(data=data, user_email=old_email)
        self.assertFalse(form.is_valid())

        # New address is the same as the old one.
        data = {"email": old_email, "email_confirmation": old_email}
        form = EditUserEmailForm(data=data, user_email=old_email)
        self.assertFalse(form.is_valid())

    def test_valid_form(self):
        old_email = "bernard@blier.fr"
        new_email = "jean@gabin.fr"
        data = {"email": new_email, "email_confirmation": new_email}
        form = EditUserEmailForm(data=data, user_email=old_email)
        self.assertTrue(form.is_valid())


class SwitchSiaeTest(TestCase):
    def test_switch_siae(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        related_siae = SiaeFactory()
        related_siae.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], siae)

        url = reverse("siaes_views:card", kwargs={"siae_id": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], siae)
        self.assertEqual(response.context["siae"], siae)

        url = reverse("dashboard:switch_siae")
        response = self.client.post(url, data={"siae_id": related_siae.pk})
        self.assertEqual(response.status_code, 302)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], related_siae)

        url = reverse("siaes_views:card", kwargs={"siae_id": related_siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], related_siae)
        self.assertEqual(response.context["siae"], related_siae)

        url = reverse("siaes_views:configure_jobs")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], related_siae)

        url = reverse("apply:list_for_siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], related_siae)

    def test_can_still_switch_to_inactive_siae_during_grace_period(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        related_siae = SiaePendingGracePeriodFactory()
        related_siae.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], siae)

        url = reverse("dashboard:switch_siae")
        response = self.client.post(url, data={"siae_id": related_siae.pk})
        self.assertEqual(response.status_code, 302)

        # User has indeed switched.
        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], related_siae)

    def test_cannot_switch_to_inactive_siae_after_grace_period(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        related_siae = SiaeAfterGracePeriodFactory()
        related_siae.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], siae)

        # Switching to that siae is not even possible in practice because
        # it does not even show up in the menu.
        url = reverse("dashboard:switch_siae")
        response = self.client.post(url, data={"siae_id": related_siae.pk})
        self.assertEqual(response.status_code, 404)

        # User is still working on the main active siae.
        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], siae)
