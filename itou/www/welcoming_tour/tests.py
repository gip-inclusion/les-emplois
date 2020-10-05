from allauth.account.adapter import get_adapter
from allauth.account.models import EmailConfirmationHMAC
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from itou.siaes.factories import SiaeWithMembershipFactory
from itou.users.factories import JobSeekerFactory, PrescriberFactory, SiaeStaffFactory


PASSWORD = "A23kf&!9jd"


def get_confirm_email_url(request, email):
    user = get_user_model().objects.get(email=email)
    user_email = user.emailaddress_set.first()
    return get_adapter().get_email_confirmation_url(request, EmailConfirmationHMAC(user_email))


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

    def verify_email(self, request):
        # User verifies its email clicking on the email he received
        confirm_email_url = get_confirm_email_url(request, self.email)
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
        response = self.client.post(url, data=post_data)
        response = self.verify_email(response.wsgi_request)

        # User should be redirected to the welcoming tour as he just signed up
        self.assertEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertTemplateUsed(response, "welcoming_tour/job_seeker.html")

    def test_new_prescriber_sees_welcoming_tour_test(self):
        session = self.client.session
        session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = {"url_history": []}
        session.save()
        prescriber = PrescriberFactory.build()
        self.email = prescriber.email
        url = reverse("signup:prescriber_user")
        post_data = {
            "first_name": prescriber.first_name,
            "last_name": prescriber.last_name,
            "email": prescriber.email,
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        response = self.client.post(url, data=post_data)
        response = self.verify_email(response.wsgi_request)

        # User should be redirected to the welcoming tour as he just signed up
        self.assertEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

    def test_new_employer_sees_welcoming_tour(self):
        employer = SiaeStaffFactory.build()
        self.email = employer.email
        siae = SiaeWithMembershipFactory()

        url = reverse("signup:siae", kwargs={"encoded_siae_id": siae.get_encoded_siae_id(), "token": siae.get_token()})
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
        response = self.client.post(url, data=post_data)
        response = self.verify_email(response.wsgi_request)

        # User should be redirected to the welcoming tour as he just signed up
        self.assertEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertTemplateUsed(response, "welcoming_tour/siae_staff.html")


class WelcomingTourExceptions(TestCase):
    def verify_email(self, email, request):
        # User verifies its email clicking on the email he received
        confirm_email_url = get_confirm_email_url(request, email)
        response = self.client.post(confirm_email_url, follow=True)
        self.assertEqual(response.status_code, 200)
        return response

    def test_new_job_seeker_is_redirected_after_welcoming_tour_test(self):
        siae = SiaeWithMembershipFactory()
        job_seeker = JobSeekerFactory.build()
        next_to = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        url = f"{reverse('signup:job_seeker')}?next={next_to}"
        post_data = {
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "email": job_seeker.email,
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        response = self.client.post(url, data=post_data)
        response = self.verify_email(job_seeker.email, response.wsgi_request)

        # The user should not be redirected to the welcoming path if he wanted to perform
        # another action before signing up.
        self.assertNotIn(response.wsgi_request.path, reverse("welcoming_tour:index"))

        # The user is redirected to "apply:step_check_job_seeker_info"
        # as birthdate and pole_emploi_id are missing from the signup form.
        # This is a valid behavior that may change in the future so
        # let's avoid too specific tests.
        self.assertTrue(response.wsgi_request.path.startswith("/apply"))

        content = mail.outbox[0].body
        self.assertIn(next_to, content)
