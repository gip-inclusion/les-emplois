import uuid

import respx
from allauth.account.models import EmailConfirmationHMAC
from django.conf import settings
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from pytest_django.asserts import assertContains, assertFormError, assertRedirects

from itou.openid_connect.france_connect import constants as fc_constants
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.www.signup.forms import JobSeekerSituationForm
from tests.cities.factories import create_test_cities
from tests.openid_connect.france_connect.tests import FC_USERINFO, mock_oauth_dance
from tests.users.factories import DEFAULT_PASSWORD, JobSeekerFactory
from tests.utils.test import parse_response_to_soup, reload_module


class TestJobSeekerSignup:
    def setup_method(self):
        [self.city] = create_test_cities(["67"], num_per_department=1)

    def test_choose_user_kind(self, client):
        url = reverse("signup:choose_user_kind")
        response = client.get(url)
        assertContains(response, "Candidat")

        response = client.post(url, data={"kind": UserKind.JOB_SEEKER})
        assertRedirects(response, reverse("signup:job_seeker_situation"))

    def test_job_seeker_signup_situation(self, client):
        """
        Test the redirects according to the chosen situations
        """

        # Check if the form page is displayed correctly.
        url = reverse("signup:job_seeker_situation")
        response = client.get(url)
        assert response.status_code == 200

        # Check if none of the boxes are checked 'some data' needed to raise
        # form error.
        post_data = {"some": "data"}
        response = client.post(url, post_data)
        assert response.status_code == 200
        assertFormError(response.context["form"], "situation", [JobSeekerSituationForm.ERROR_NOTHING_CHECKED])

        # Check if one of eligibility criterion is checked.
        next_url = reverse("signup:job_seeker_nir")
        for choice in JobSeekerSituationForm.ELIGIBLE_SITUATION:
            post_data = {"situation": [choice]}
            response = client.post(url, data=post_data)
            assert response.status_code == 302
            assertRedirects(response, next_url)

            post_data["situation"].append("autre")
            response = client.post(url, data=post_data)
            assert response.status_code == 302
            assertRedirects(response, next_url)

        # Check if all the eligibility criteria are checked.
        post_data = {"situation": JobSeekerSituationForm.ELIGIBLE_SITUATION}
        response = client.post(url, data=post_data)
        assert response.status_code == 302
        assertRedirects(response, next_url)

        # Check if "Autre" is the only one checked.
        post_data = {"situation": "autre"}
        response = client.post(url, data=post_data)
        assert response.status_code == 302
        next_url = reverse("signup:job_seeker_situation_not_eligible")
        assertRedirects(response, next_url)

        # Check not eligible destination page.
        url = reverse("signup:job_seeker_situation_not_eligible")
        response = client.get(url)
        assert response.status_code == 200

    def test_job_seeker_nir(self, client):
        nir = "141068078200557"

        # Get the NIR.
        # It will be saved in the next view.
        url = reverse("signup:job_seeker_nir")
        response = client.get(url)
        assert response.status_code == 200

        post_data = {"nir": nir}
        response = client.post(url, post_data)
        assertRedirects(response, reverse("signup:job_seeker"))
        assert global_constants.ITOU_SESSION_NIR_KEY in list(client.session.keys())
        assert client.session.get(global_constants.ITOU_SESSION_NIR_KEY)

        # NIR is stored with user information.
        url = reverse("signup:job_seeker")
        response = client.get(url)
        assert response.status_code == 200
        # Since provided NIR starts with a 1, suggest Monsieur title
        assert response.context["form"]["title"].initial == "M"

        address_line_1 = "Test adresse"
        address_line_2 = "Test adresse complémentaire"
        post_code = self.city.post_codes[0]

        post_data = {
            "title": "M",
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe+1@company.com",
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
            "address_line_1": address_line_1,
            "address_line_2": address_line_2,
            "post_code": post_code,
            "city_name": self.city.name,
            "city": self.city.slug,
        }

        response = client.post(url, data=post_data)
        assert response.status_code == 302
        assertRedirects(response, reverse("account_email_verification_sent"))

        job_seeker = User.objects.get(email=post_data["email"])
        assert nir == job_seeker.jobseeker_profile.nir
        assert job_seeker.title == "M"
        assert job_seeker.has_jobseeker_profile

    def test_job_seeker_temporary_nir(self, client):
        """
        For the moment, we don't handle temporary social numbers.
        Skipping NIR verification is allowed if a temporary one should be used instead.
        """

        # Temporary numbers don't have a consistent format.
        nir = "1234567895GHTUI"

        url = reverse("signup:job_seeker_nir")
        post_data = {"nir": nir}
        response = client.post(url, post_data)
        assert response.status_code == 200
        assert not response.context.get("form").is_valid()

        post_data = {"nir": nir, "skip": 1}
        response = client.post(url, post_data)
        assertRedirects(response, reverse("signup:job_seeker"))
        assert global_constants.ITOU_SESSION_NIR_KEY not in list(client.session.keys())
        assert not client.session.get(global_constants.ITOU_SESSION_NIR_KEY)

        # Temporary NIR is not stored with user information.
        url = reverse("signup:job_seeker")
        response = client.get(url)
        assert response.status_code == 200
        # Since no NIR was provided (or it was a temporary number), suggest nothing
        assert response.context["form"]["title"].initial is None

        address_line_1 = "Test adresse"
        address_line_2 = "Test adresse complémentaire"
        post_code = self.city.post_codes[0]

        post_data = {
            "title": "M",
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe+2@company.com",
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
            "address_line_1": address_line_1,
            "address_line_2": address_line_2,
            "post_code": post_code,
            "city_name": self.city.name,
            "city": self.city.slug,
        }

        response = client.post(url, data=post_data)
        assert response.status_code == 302
        assertRedirects(response, reverse("account_email_verification_sent"))

        job_seeker = User.objects.get(email=post_data["email"])
        assert job_seeker.jobseeker_profile.nir == ""
        assert job_seeker.title == "M"
        assert job_seeker.has_jobseeker_profile

    def test_job_seeker_signup(self, client, snapshot):
        """Job-seeker signup."""
        # NIR is set on a previous step and tested separately.
        # See self.test_job_seeker_nir
        nir = "141068078200557"
        client.post(reverse("signup:job_seeker_nir"), {"nir": nir})

        url = reverse("signup:job_seeker")
        response = client.get(url)
        assert response.status_code == 200
        form = parse_response_to_soup(response, selector="form.js-prevent-multiple-submit")
        assert str(form) == snapshot(name="job_seeker_signup_form")

        address_line_1 = "Test adresse"
        address_line_2 = "Test adresse complémentaire"
        post_code = self.city.post_codes[0]

        post_data = {
            "title": "M",
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe+3@company.com",
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
            "address_line_1": address_line_1,
            "address_line_2": address_line_2,
            "post_code": post_code,
            "city_name": self.city.name,
            "city": self.city.slug,
        }

        response = client.post(url, data=post_data)
        assert response.status_code == 302
        assertRedirects(response, reverse("account_email_verification_sent"))

        # Check `User` state.
        user = User.objects.get(email=post_data["email"])
        # `username` should be a valid UUID, see `User.generate_unique_username()`.
        assert user.username == uuid.UUID(user.username, version=4).hex
        assert user.kind == UserKind.JOB_SEEKER
        assert user.title == "M"
        assert user.has_jobseeker_profile

        # Check `EmailAddress` state.
        assert user.emailaddress_set.count() == 1
        user_email = user.emailaddress_set.first()
        assert not user_email.verified

        # Check sent email.
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert "Confirmez votre adresse e-mail" in email.subject
        assert "Afin de finaliser votre inscription, cliquez sur le lien suivant" in email.body
        assert email.from_email == settings.DEFAULT_FROM_EMAIL
        assert len(email.to) == 1
        assert email.to[0] == user.email

        # User cannot log in until confirmation.
        post_data = {"login": user.email, "password": DEFAULT_PASSWORD}
        url = reverse("login:job_seeker")
        response = client.post(url, data=post_data)
        assert response.status_code == 302
        assert response.url == reverse("account_email_verification_sent")

        # Confirm email + auto login.
        confirmation_token = EmailConfirmationHMAC(user_email).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        # User clicks on the confirm link in the email, that is a GET request.
        response = client.get(confirm_email_url)
        assertRedirects(response, reverse("welcoming_tour:index"))
        user_email = user.emailaddress_set.first()
        assert user_email.verified

        response = client.get(confirm_email_url)
        # Uses the custom template to display errors.
        assertContains(
            response,
            f"""
            <div class="alert alert-danger">
                <p>Ce lien de confirmation d'adresse e-mail a expiré ou n'est pas valide.</p>
                <p class="mb-0">
                Veuillez lancer <a href="{reverse('account_email')}">une nouvelle demande de confirmation</a>.
                </p>
            </div>
            """,
            html=True,
            count=1,
        )

    def test_job_seeker_signup_with_existing_email(self, client):
        JobSeekerFactory(email="alice@evil.com")
        url = reverse("signup:job_seeker")
        response = client.post(
            url,
            {
                "title": "MME",
                "first_name": "Alice",
                "last_name": "Evil",
                "email": "alice@evil.com",
                "password1": "Véry_S3C®3T!",
                "password2": "Véry_S3C®3T!",
                "address_line_1": "Test address_line_1",
                "address_line_2": "Test address_line_2",
                "post_code": "87000",
                "city_name": "Limoges",
                "city": "limoges",
            },
        )
        assert response.status_code == 200
        assert response.context["form"].errors == {
            "email": ["Un autre utilisateur utilise déjà cette adresse e-mail."]
        }

    @respx.mock
    @override_settings(
        FRANCE_CONNECT_BASE_URL="https://france.connect.fake",
        FRANCE_CONNECT_CLIENT_ID="IC_CLIENT_ID_123",
        FRANCE_CONNECT_CLIENT_SECRET="IC_CLIENT_SECRET_123",
    )
    @reload_module(fc_constants)
    def test_job_seeker_nir_with_france_connect(self, client):
        # NIR is set on a previous step and tested separately.
        # See self.test_job_seeker_nir
        nir = "141068078200557"
        client.post(reverse("signup:job_seeker_nir"), {"nir": nir})
        assert global_constants.ITOU_SESSION_NIR_KEY in list(client.session.keys())
        assert client.session.get(global_constants.ITOU_SESSION_NIR_KEY)

        url = reverse("signup:job_seeker")
        response = client.get(url)
        fc_url = reverse("france_connect:authorize")
        assertContains(response, fc_url)

        # New created job seeker has no title and is redirected to complete its infos
        mock_oauth_dance(client, expected_route="dashboard:edit_user_info")
        job_seeker = User.objects.get(email=FC_USERINFO["email"])
        assert nir == job_seeker.jobseeker_profile.nir
        assert job_seeker.has_jobseeker_profile

    @respx.mock
    @override_settings(
        FRANCE_CONNECT_BASE_URL="https://france.connect.fake",
        FRANCE_CONNECT_CLIENT_ID="IC_CLIENT_ID_123",
        FRANCE_CONNECT_CLIENT_SECRET="IC_CLIENT_SECRET_123",
    )
    @reload_module(fc_constants)
    def test_job_seeker_temporary_nir_with_france_connect(self, client):
        # temporary NIR is discarded on a previous step and tested separately.
        # See self.test_job_seeker_temporary_nir

        assert global_constants.ITOU_SESSION_NIR_KEY not in list(client.session.keys())
        assert not client.session.get(global_constants.ITOU_SESSION_NIR_KEY)

        # Temporary NIR is not stored with user information.
        url = reverse("signup:job_seeker")
        response = client.get(url)
        fc_url = reverse("france_connect:authorize")
        assertContains(response, fc_url)

        # New created job seeker has no title and is redirected to complete its infos
        mock_oauth_dance(client, expected_route="dashboard:edit_user_info")
        job_seeker = User.objects.get(email=FC_USERINFO["email"])
        assert not job_seeker.jobseeker_profile.nir
        assert job_seeker.has_jobseeker_profile
