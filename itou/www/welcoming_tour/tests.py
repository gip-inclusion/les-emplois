from allauth.account.models import EmailConfirmationHMAC
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from itou.siaes.factories import SiaeWithMembershipFactory
from itou.users.factories import JobSeekerFactory, PrescriberFactory, SiaeStaffFactory


PASSWORD = "A23kf&!9jd"


class WelcomingTourTest(TestCase):
    def setUp(self):
        self.email = None

    def tearDown(self):
        self.client.logout()

        response = self.client.post(
            reverse("account_login"), follow=True, data={"login": self.email, "password": PASSWORD}
        )

        self.assertNotEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertContains(response, "Revoir le message")

    def verify_email(self):
        user = get_user_model().objects.get(email=self.email)
        user_email = user.emailaddress_set.first()

        # User verifies its email clicking on the email he received
        confirmation_token = EmailConfirmationHMAC(user_email).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        response = self.client.post(confirm_email_url, follow=True)
        self.assertEqual(response.status_code, 200)
        return response

    def test_new_job_seeker_sees_welcoming_tour_test(self):
        job_seeker = JobSeekerFactory.build()
        self.email = job_seeker.email
        url = reverse("signup:job_seeker")
        post_data = {
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "email": job_seeker.email,
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        self.client.post(url, data=post_data)
        response = self.verify_email()

        # User should be redirected to the welcoming tour as he just signed up
        self.assertEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertTemplateUsed(response, "welcoming_tour/job_seeker.html")

    def test_new_prescriber_sees_welcoming_tour_test(self):
        prescriber = PrescriberFactory.build()
        self.email = prescriber.email
        url = reverse("signup:prescriber_orienter")
        post_data = {
            "first_name": prescriber.first_name,
            "last_name": prescriber.last_name,
            "email": prescriber.email,
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        self.client.post(url, data=post_data)
        response = self.verify_email()

        # User should be redirected to the welcoming tour as he just signed up
        self.assertEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

    def test_new_employer_sees_welcoming_tour(self):
        # Employer signs up
        employer = SiaeStaffFactory.build()
        siae = SiaeWithMembershipFactory()
        self.email = employer.email

        url = reverse("signup:siae")
        post_data = {
            "encoded_siae_id": siae.get_encoded_siae_id(),
            "token": siae.get_token(),
            "siret": siae.siret,
            "kind": siae.kind,
            "siae_name": siae.display_name,
            "first_name": employer.first_name,
            "last_name": employer.last_name,
            "email": employer.email,
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        self.client.post(url, data=post_data)
        response = self.verify_email()

        # User should be redirected to the welcoming tour as he just signed up
        self.assertEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertTemplateUsed(response, "welcoming_tour/siae_staff.html")
