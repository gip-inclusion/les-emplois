import respx
from allauth.account.adapter import get_adapter
from allauth.account.models import EmailConfirmationHMAC
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from itou.openid_connect.inclusion_connect.testing import InclusionConnectBaseTestCase
from itou.openid_connect.inclusion_connect.tests import mock_oauth_dance
from itou.siaes.factories import SiaeFactory
from itou.users.enums import KIND_PRESCRIBER, KIND_SIAE_STAFF
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory
from itou.users.models import User
from itou.utils import constants as global_constants


def get_confirm_email_url(request, email):
    user = User.objects.get(email=email)
    user_email = user.emailaddress_set.first()
    return get_adapter().get_email_confirmation_url(request, EmailConfirmationHMAC(user_email))


class WelcomingTourTest(InclusionConnectBaseTestCase):
    def setUp(self):
        self.email = None
        super().setUp()

    def verify_email(self, request, email):
        # User verifies its email clicking on the email he received
        confirm_email_url = get_confirm_email_url(request, email)
        response = self.client.post(confirm_email_url, follow=True)
        self.assertEqual(response.status_code, 200)
        return response

    def test_new_job_seeker_sees_welcoming_tour_test(self):
        job_seeker = JobSeekerFactory.build()

        # First signup step: job seeker NIR.
        url = reverse("signup:job_seeker_nir")
        self.client.post(url, {"nir": job_seeker.nir, "confirm": 1})

        # Second signup step: job seeker credentials.
        url = reverse("signup:job_seeker")
        post_data = {
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "email": job_seeker.email,
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = self.client.post(url, data=post_data)
        response = self.verify_email(response.wsgi_request, email=job_seeker.email)

        # User should be redirected to the welcoming tour as he just signed up
        self.assertEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertTemplateUsed(response, "welcoming_tour/job_seeker.html")

        self.client.logout()
        response = self.client.post(
            reverse("login:job_seeker"), follow=True, data={"login": job_seeker.email, "password": DEFAULT_PASSWORD}
        )
        self.assertNotEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertContains(response, "Revoir le message")

    @respx.mock
    def test_new_prescriber_sees_welcoming_tour_test(self):
        session = self.client.session
        session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = {"url_history": []}
        session.save()
        response = mock_oauth_dance(self, KIND_PRESCRIBER, assert_redirects=False)
        response = self.client.get(response.url, follow=True)

        # User should be redirected to the welcoming tour as he just signed up
        self.assertEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        self.client.logout()
        response = mock_oauth_dance(self, KIND_PRESCRIBER, assert_redirects=False)
        response = self.client.get(response.url, follow=True)
        self.assertNotEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertContains(response, "Revoir le message")

    @respx.mock
    def test_new_employer_sees_welcoming_tour(self):
        siae = SiaeFactory(with_membership=True)
        encoded_siae_id = siae.get_encoded_siae_id()
        token = siae.get_token()
        previous_url = reverse("signup:siae_user", args=(encoded_siae_id, token))
        next_url = reverse("signup:siae_join", args=(encoded_siae_id, token))
        response = mock_oauth_dance(
            self,
            KIND_SIAE_STAFF,
            assert_redirects=False,
            previous_url=previous_url,
            next_url=next_url,
        )
        response = self.client.get(response.url, follow=True)

        # User should be redirected to the welcoming tour as he just signed up
        self.assertEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertTemplateUsed(response, "welcoming_tour/siae_staff.html")

        self.client.logout()
        response = mock_oauth_dance(self, KIND_SIAE_STAFF, assert_redirects=False)
        response = self.client.get(response.url, follow=True)
        self.assertNotEqual(response.wsgi_request.path, reverse("welcoming_tour:index"))
        self.assertContains(response, "Revoir le message")


class WelcomingTourExceptions(TestCase):
    def verify_email(self, email, request):
        # User verifies its email clicking on the email he received
        confirm_email_url = get_confirm_email_url(request, email)
        response = self.client.post(confirm_email_url, follow=True)
        self.assertEqual(response.status_code, 200)
        return response

    def test_new_job_seeker_is_redirected_after_welcoming_tour_test(self):
        siae = SiaeFactory(with_membership=True)
        job_seeker = JobSeekerFactory.build()

        # First signup step: job seeker NIR.
        next_to = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        url = f"{reverse('signup:job_seeker_nir')}?next={next_to}"
        self.client.post(url, {"nir": job_seeker.nir, "confirm": 1})

        # Second signup step: job seeker credentials.
        url = f"{reverse('signup:job_seeker')}?next={next_to}"
        post_data = {
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "email": job_seeker.email,
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
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
