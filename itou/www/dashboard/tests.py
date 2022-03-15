from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.conf import settings
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from itou.employee_record.factories import EmployeeRecordFactory
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.factories import (
    JobApplicationSentByAuthorizedPrescriberOrganizationFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationWithApprovalFactory,
)
from itou.job_applications.notifications import (
    NewQualifiedJobAppEmployersNotification,
    NewSpontaneousJobAppEmployersNotification,
)
from itou.prescribers import factories as prescribers_factories
from itou.siaes.factories import (
    SiaeAfterGracePeriodFactory,
    SiaeFactory,
    SiaePendingGracePeriodFactory,
    SiaeWithMembershipAndJobsFactory,
    SiaeWithMembershipFactory,
)
from itou.siaes.models import Siae
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, PrescriberFactory, SiaeStaffFactory
from itou.users.models import User
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

        expected_message = "votre compte n'est malheureusement plus actif"
        self.assertContains(response, expected_message)

    def test_dashboard_eiti(self):
        siae = SiaeWithMembershipFactory(kind=Siae.KIND_EITI)
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_dashboard_displays_asp_badge(self):
        siae = SiaeWithMembershipFactory(kind=Siae.KIND_EI)
        other_siae = SiaeWithMembershipFactory(kind=Siae.KIND_ETTI)
        last_siae = SiaeWithMembershipFactory(kind=Siae.KIND_ETTI)

        user = siae.members.first()
        user.siae_set.add(other_siae)
        user.siae_set.add(last_siae)

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gérer mes fiches salarié")
        self.assertNotContains(response, "badge-danger")
        self.assertEqual(response.context["num_rejected_employee_records"], 0)

        # create rejected job applications
        job_application = JobApplicationWithApprovalFactory(to_siae=siae)
        EmployeeRecordFactory(job_application=job_application, status=EmployeeRecord.Status.REJECTED)
        EmployeeRecordFactory(job_application=job_application, status=EmployeeRecord.Status.REJECTED)

        other_job_application = JobApplicationWithApprovalFactory(to_siae=other_siae)
        EmployeeRecordFactory(job_application=other_job_application, status=EmployeeRecord.Status.REJECTED)

        session = self.client.session

        # select the first SIAE's in the session
        session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = siae.pk
        session.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "badge-danger")
        self.assertEqual(response.context["num_rejected_employee_records"], 2)

        # select the second SIAE's in the session
        session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = other_siae.pk
        session.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "badge-danger")
        self.assertEqual(response.context["num_rejected_employee_records"], 1)

        # select the third SIAE's in the session
        session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = last_siae.pk
        session.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["num_rejected_employee_records"], 0)

    def test_dashboard_agreements_and_job_postings(self):
        for kind in [Siae.KIND_AI, Siae.KIND_EI, Siae.KIND_EITI, Siae.KIND_ACI, Siae.KIND_EITI, Siae.KIND_ACIPHC]:
            with self.subTest(f"should display when siae_kind={kind}"):
                siae = SiaeWithMembershipFactory(kind=kind)
                user = siae.members.first()
                self.client.login(username=user.email, password=DEFAULT_PASSWORD)

                response = self.client.get(reverse("dashboard:index"))
                self.assertContains(response, "Prolonger ou suspendre un agrément émis par Pôle emploi")
                self.assertContains(response, "Déclarer une embauche")

        for kind in [Siae.KIND_EA, Siae.KIND_EATT, Siae.KIND_GEIQ, Siae.KIND_OPCS]:
            with self.subTest(f"should not display when siae_kind={kind}"):
                siae = SiaeWithMembershipFactory(kind=kind)
                user = siae.members.first()
                self.client.login(username=user.email, password=DEFAULT_PASSWORD)

                response = self.client.get(reverse("dashboard:index"))
                self.assertNotContains(response, "Prolonger ou suspendre un agrément émis par Pôle emploi")
                self.assertNotContains(response, "Déclarer une embauche")

    def test_dashboard_can_create_siae_antenna(self):
        for kind in [Siae.KIND_EA, Siae.KIND_EATT, Siae.KIND_GEIQ]:
            with self.subTest(f"antennas freely created without a convention siae_kind={kind}"):
                siae = SiaeWithMembershipFactory(kind=kind, convention=None)
                user = siae.members.first()
                self.client.login(username=user.email, password=DEFAULT_PASSWORD)
                response = self.client.get(reverse("dashboard:index"))
                self.assertContains(response, "Créer/rejoindre une autre structure")

        # but disabled specifically for OPCS
        siae = SiaeWithMembershipFactory(kind=Siae.KIND_OPCS)
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, "Créer/rejoindre une autre structure")


class EditUserInfoViewTest(TestCase):
    def test_edit(self):
        user = JobSeekerFactory()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(id=user.id)
        self.assertEqual(user.first_name, post_data["first_name"])
        self.assertEqual(user.last_name, post_data["last_name"])
        self.assertEqual(user.phone, post_data["phone"])
        self.assertEqual(user.birthdate.strftime("%d/%m/%Y"), post_data["birthdate"])

        # Ensure that the job seeker cannot edit email here.
        self.assertNotEqual(user.email, post_data["email"])


class EditJobSeekerInfo(TestCase):
    def test_edit_by_siae(self):
        job_application = JobApplicationSentByPrescriberFactory()
        user = job_application.to_siae.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        back_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_application_id": job_application.pk})
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
        }
        response = self.client.post(url, data=post_data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, back_url)

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        self.assertEqual(job_seeker.first_name, post_data["first_name"])
        self.assertEqual(job_seeker.last_name, post_data["last_name"])
        self.assertEqual(job_seeker.birthdate.strftime("%d/%m/%Y"), post_data["birthdate"])
        self.assertEqual(job_seeker.phone, post_data["phone"])

    def test_edit_by_prescriber(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        user = job_application.sender

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_edit_by_prescriber_of_organization(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        prescriber = job_application.sender

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = prescriber
        job_application.job_seeker.save()

        # Log as other member of the same organization
        other_prescriber = PrescriberFactory()
        prescribers_factories.PrescriberMembershipFactory(
            user=other_prescriber, organization=job_application.sender_prescriber_organization
        )
        self.client.login(username=other_prescriber.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_edit_autonomous_not_allowed(self):
        job_application = JobApplicationSentByPrescriberFactory()
        # The job seeker manages his own personal information (autonomous)
        user = job_application.sender
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_application_id": job_application.pk})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_edit_not_allowed(self):
        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application = JobApplicationSentByPrescriberFactory(job_seeker__created_by=PrescriberFactory())

        # Lambda prescriber not member of the sender organization
        prescriber = PrescriberFactory()
        self.client.login(username=prescriber.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_application_id": job_application.pk})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_edit_email_when_unconfirmed(self):
        """
        The SIAE can edit the email of a jobseeker it works with, provided he did not confirm its email.
        """
        new_email = "bidou@yopmail.com"
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        job_application = JobApplicationSentByPrescriberFactory(to_siae=siae, job_seeker__created_by=user)

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        back_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_application_id": job_application.pk})
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        self.assertContains(response, "Adresse électronique")

        post_data = {
            "email": new_email,
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
        }
        response = self.client.post(url, data=post_data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, back_url)

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        self.assertEqual(job_seeker.email, new_email)

    def test_edit_email_when_confirmed(self):
        new_email = "bidou@yopmail.com"
        job_application = JobApplicationSentByPrescriberFactory()
        user = job_application.to_siae.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        # Confirm job seeker email
        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        EmailAddress.objects.create(user=job_seeker, email=job_seeker.email, verified=True)

        # Now the SIAE wants to edit the jobseeker email. The field is not available, and it cannot be bypassed
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        back_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_application_id": job_application.pk})
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        self.assertNotContains(response, "Adresse électronique")

        post_data = {
            "email": new_email,
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
        }
        response = self.client.post(url, data=post_data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, back_url)

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        # The email is not changed, but other fields are taken into account
        self.assertNotEqual(job_seeker.email, new_email)
        self.assertEqual(job_seeker.phone, post_data["phone"])
        self.assertEqual(job_seeker.birthdate.strftime("%d/%m/%Y"), post_data["birthdate"])


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
        url = reverse("login:job_seeker")
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context_data["form"].is_valid())

        # User cannot log in until confirmation
        post_data = {"login": new_email, "password": DEFAULT_PASSWORD}
        url = reverse("login:job_seeker")
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("account_email_verification_sent"))

        # User receives an email to confirm his new address.
        email = mail.outbox[0]
        self.assertIn("Confirmez votre adresse e-mail", email.subject)
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

        url = reverse("siaes_views:job_description_list")
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


class EditUserPreferencesTest(TestCase):
    def test_employer_opt_in_siae_no_job_description(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        recipient = user.siaemembership_set.get(siae=siae)
        form_name = "new_job_app_notification_form"

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Recipient's notifications are empty for the moment.
        self.assertFalse(recipient.notifications)

        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Recipients are subscribed to spontaneous notifications by default,
        # the form should reflect that.
        self.assertTrue(response.context[form_name].fields["spontaneous"].initial)

        data = {"spontaneous": True}
        response = self.client.post(url, data=data)

        self.assertEqual(response.status_code, 302)

        recipient.refresh_from_db()
        self.assertTrue(recipient.notifications)
        self.assertTrue(NewSpontaneousJobAppEmployersNotification.is_subscribed(recipient=recipient))

    def test_employer_opt_in_siae_with_job_descriptions(self):
        siae = SiaeWithMembershipAndJobsFactory()
        user = siae.members.first()
        job_descriptions_pks = list(siae.job_description_through.values_list("pk", flat=True))
        recipient = user.siaemembership_set.get(siae=siae)
        form_name = "new_job_app_notification_form"
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Recipient's notifications are empty for the moment.
        self.assertFalse(recipient.notifications)

        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Recipients are subscribed to spontaneous notifications by default,
        # the form should reflect that.
        self.assertEqual(response.context[form_name].fields["qualified"].initial, job_descriptions_pks)

        data = {"qualified": job_descriptions_pks}
        response = self.client.post(url, data=data)
        self.assertEqual(response.status_code, 302)

        recipient.refresh_from_db()
        self.assertTrue(recipient.notifications)

        for pk in job_descriptions_pks:
            self.assertTrue(
                NewQualifiedJobAppEmployersNotification.is_subscribed(recipient=recipient, subscribed_pk=pk)
            )

    def test_employer_opt_out_siae_no_job_descriptions(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        recipient = user.siaemembership_set.get(siae=siae)
        form_name = "new_job_app_notification_form"
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Recipient's notifications are empty for the moment.
        self.assertFalse(recipient.notifications)

        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Recipients are subscribed to spontaneous notifications by default,
        # the form should reflect that.
        self.assertTrue(response.context[form_name].fields["spontaneous"].initial)

        data = {"spontaneous": False}
        response = self.client.post(url, data=data)

        self.assertEqual(response.status_code, 302)

        recipient.refresh_from_db()
        self.assertTrue(recipient.notifications)
        self.assertFalse(NewSpontaneousJobAppEmployersNotification.is_subscribed(recipient=recipient))

    def test_employer_opt_out_siae_with_job_descriptions(self):
        siae = SiaeWithMembershipAndJobsFactory()
        user = siae.members.first()
        job_descriptions_pks = list(siae.job_description_through.values_list("pk", flat=True))
        recipient = user.siaemembership_set.get(siae=siae)
        form_name = "new_job_app_notification_form"
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Recipient's notifications are empty for the moment.
        self.assertFalse(recipient.notifications)

        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Recipients are subscribed to qualified notifications by default,
        # the form should reflect that.
        self.assertEqual(response.context[form_name].fields["qualified"].initial, job_descriptions_pks)

        # The recipient opted out from every notification.
        data = {"spontaneous": False}
        response = self.client.post(url, data=data)
        self.assertEqual(response.status_code, 302)

        recipient.refresh_from_db()
        self.assertTrue(recipient.notifications)

        for _i, pk in enumerate(job_descriptions_pks):
            self.assertFalse(
                NewQualifiedJobAppEmployersNotification.is_subscribed(recipient=recipient, subscribed_pk=pk)
            )


class EditUserPreferencesExceptionsTest(TestCase):
    def test_not_allowed_user(self):
        # Only employers can currently access the Preferences page.

        prescriber = PrescriberFactory()
        self.client.login(username=prescriber.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        job_seeker = JobSeekerFactory()
        self.client.login(username=job_seeker.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
