import respx
from allauth.account.adapter import get_adapter
from allauth.account.models import EmailConfirmationHMAC
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from itou.users.enums import KIND_EMPLOYER, KIND_PRESCRIBER
from itou.users.models import User
from itou.utils import constants as global_constants
from tests.companies.factories import CompanyFactory
from tests.openid_connect.test import sso_parametrize
from tests.users.factories import DEFAULT_PASSWORD, JobSeekerFactory


def get_confirm_email_url(request, email):
    user = User.objects.get(email=email)
    user_email = user.emailaddress_set.first()
    return get_adapter().get_email_confirmation_url(request, EmailConfirmationHMAC(user_email))


def verify_email(client, email, request):
    # User verifies its email clicking on the email he received
    confirm_email_url = get_confirm_email_url(request, email)
    response = client.get(confirm_email_url, follow=True)
    assert response.status_code == 200
    return response


class TestWelcomingTour:
    def test_new_job_seeker_sees_welcoming_tour_test(self, client):
        job_seeker = JobSeekerFactory.build(born_in_france=True)

        # First signup step: job seeker personal info.
        url = reverse("signup:job_seeker")
        post_data = {
            "nir": job_seeker.jobseeker_profile.nir,
            "title": job_seeker.title,
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "birthdate": job_seeker.jobseeker_profile.birthdate,
            "birth_place": job_seeker.jobseeker_profile.birth_place_id,
            "birth_country": job_seeker.jobseeker_profile.birth_country_id,
            "email": job_seeker.email,
        }
        client.post(url, data=post_data)

        # Second signup step: job seeker credentials.
        url = reverse("signup:job_seeker_credentials")
        post_data = {
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 302
        response = verify_email(client, job_seeker.email, response.wsgi_request)

        # User should be redirected to the welcoming tour as he just signed up
        assert response.wsgi_request.path == reverse("welcoming_tour:index")
        assertTemplateUsed(response, "welcoming_tour/job_seeker.html")

    @sso_parametrize
    @respx.mock
    def test_new_prescriber_sees_welcoming_tour_test(self, client, sso_setup):
        session = client.session
        session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = {"url_history": []}
        session.save()
        response = sso_setup.mock_oauth_dance(client, KIND_PRESCRIBER)
        response = client.get(response.url, follow=True)

        # User should be redirected to the welcoming tour as he just signed up
        assert response.wsgi_request.path == reverse("welcoming_tour:index")
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

    @sso_parametrize
    @respx.mock
    def test_new_employer_sees_welcoming_tour(self, client, sso_setup):
        company = CompanyFactory(with_membership=True)
        token = company.get_token()
        previous_url = reverse("signup:employer", args=(company.pk, token))
        next_url = reverse("signup:company_join", args=(company.pk, token))
        response = sso_setup.mock_oauth_dance(
            client,
            KIND_EMPLOYER,
            previous_url=previous_url,
            next_url=next_url,
        )
        response = client.get(response.url, follow=True)

        # User should be redirected to the welcoming tour as he just signed up
        assert response.wsgi_request.path == reverse("welcoming_tour:index")
        assertTemplateUsed(response, "welcoming_tour/employer.html")


class TestWelcomingTourExceptions:
    def test_new_job_seeker_is_redirected_after_welcoming_tour_test(self, client, mailoutbox):
        company = CompanyFactory(with_membership=True)
        job_seeker = JobSeekerFactory.build(born_in_france=True)

        # First signup step: job seeker personal info.
        next_to = reverse("apply:start", kwargs={"company_pk": company.pk})
        url = f"{reverse('signup:job_seeker')}?next={next_to}"
        post_data = {
            "nir": job_seeker.jobseeker_profile.nir,
            "title": job_seeker.title,
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "email": job_seeker.email,
            "birthdate": job_seeker.jobseeker_profile.birthdate,
            "birth_place": job_seeker.jobseeker_profile.birth_place_id,
            "birth_country": job_seeker.jobseeker_profile.birth_country_id,
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 302  # Destination verified in signup tests
        assert client.session.get(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY)

        # Second signup step: job seeker credentials.
        url = f"{reverse('signup:job_seeker_credentials')}?next={next_to}"
        post_data = {
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 302
        response = verify_email(client, job_seeker.email, response.wsgi_request)

        # The user should not be redirected to the welcoming path if he wanted to perform
        # another action before signing up.
        assert response.wsgi_request.path not in reverse("welcoming_tour:index")

        # The user is redirected to "job_seekers_views:check_job_seeker_info"
        # as birthdate and pole_emploi_id are missing from the signup form.
        # This is a valid behavior that may change in the future so
        # let's avoid too specific tests.
        assert response.wsgi_request.path.startswith("/job-seekers")

        content = mailoutbox[0].body
        assert next_to in content
