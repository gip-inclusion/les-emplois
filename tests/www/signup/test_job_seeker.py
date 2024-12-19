import uuid

import pytest
import respx
from allauth.account.models import EmailConfirmationHMAC
from django.conf import settings
from django.contrib import messages
from django.test import override_settings
from django.urls import reverse
from pytest_django.asserts import assertContains, assertFormError, assertMessages, assertRedirects

from itou.openid_connect.france_connect import constants as fc_constants
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.widgets import DuetDatePickerWidget
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
        next_url = reverse("signup:job_seeker")
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

    def _test_job_seeker_signup_forms(self, client, nir, **extra_signup_kwargs):
        # auxiliary function tests the forms flow for JobSeeker creation with parameterized NIR
        url = reverse("signup:job_seeker")
        response = client.get(url)
        assert response.status_code == 200

        job_seeker_data = JobSeekerFactory.build()
        post_data = {
            "nir": nir,
            "title": job_seeker_data.title,
            "first_name": job_seeker_data.first_name,
            "last_name": job_seeker_data.last_name,
            "email": job_seeker_data.email,
            "birthdate": job_seeker_data.jobseeker_profile.birthdate,
            **extra_signup_kwargs,
        }

        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("signup:job_seeker_credentials"))
        assert client.session.get(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY)

        url = reverse("signup:job_seeker_credentials")
        response = client.get(url)
        assert response.status_code == 200

        post_data = {
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("account_email_verification_sent"))

        # Test session cleanup
        assert client.session.get(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY) is None

        user = User.objects.get(email=job_seeker_data.email)
        assert job_seeker_data.title == user.title
        assert user.has_jobseeker_profile

        return user

    def test_job_seeker_signup(self, client, snapshot, mailoutbox):
        url = reverse("signup:job_seeker")
        response = client.get(url)
        assert response.status_code == 200
        replace_in_attr = [("max", str(DuetDatePickerWidget.max_birthdate()), "2008-10-23")]
        form = parse_response_to_soup(response, selector="form.js-format-nir", replace_in_attr=replace_in_attr)
        assert str(form) == snapshot(name="job_seeker_signup_form")

        nir = "141068078200557"
        user = self._test_job_seeker_signup_forms(client, nir)
        assert user.jobseeker_profile.nir == nir

        # `username` should be a valid UUID, see `User.generate_unique_username()`.
        assert user.username == uuid.UUID(user.username, version=4).hex
        assert user.kind == UserKind.JOB_SEEKER

        # Check `EmailAddress` state.
        assert user.emailaddress_set.count() == 1
        user_email = user.emailaddress_set.first()
        assert not user_email.verified

        # Check sent email.
        assert len(mailoutbox) == 1
        email = mailoutbox[0]
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
            <div class="alert alert-danger" role="status">
                <p class="mb-2">Ce lien de confirmation d'adresse e-mail a expiré ou n'est pas valide.</p>
                <p class="mb-0">
                Veuillez lancer <a href="{reverse('account_email')}">une nouvelle demande de confirmation</a>.
                </p>
            </div>
            """,
            html=True,
            count=1,
        )

    def test_job_seeker_signup_temporary_nir(self, client):
        """
        For the moment, we don't handle temporary social numbers.
        Skipping NIR verification is allowed if a temporary one should be used instead.
        """

        # Temporary numbers don't have a consistent format.
        nir = "1234567895GHTUI"

        job_seeker_data = JobSeekerFactory.build()
        post_data = {
            "nir": nir,
            "title": job_seeker_data.title,
            "first_name": job_seeker_data.first_name,
            "last_name": job_seeker_data.last_name,
            "email": job_seeker_data.email,
            "birthdate": job_seeker_data.jobseeker_profile.birthdate,
        }

        # Temporary NIR not considered valid.
        url = reverse("signup:job_seeker")
        response = client.post(url, post_data)
        assert response.status_code == 200
        assert not response.context.get("form").is_valid()

        # Possible to submit the form without the NIR.
        user = self._test_job_seeker_signup_forms(client, nir, skip=1)

        # Temporary NIR is not stored with user information.
        assert user.jobseeker_profile.nir == ""

    def test_job_seeker_signup_temporary_nir_resubmission(self, client):
        # Temporary numbers don't have a consistent format.
        nir = "1234567895GHTUI"

        job_seeker_data = JobSeekerFactory.build()
        post_data = {
            "nir": nir,
            "title": job_seeker_data.title,
            "first_name": job_seeker_data.first_name,
            "last_name": job_seeker_data.last_name,
            "email": job_seeker_data.email,
            "birthdate": job_seeker_data.jobseeker_profile.birthdate,
        }

        # Temporary NIR not considered valid.
        url = reverse("signup:job_seeker")
        response = client.post(url, post_data)
        assert response.status_code == 200
        assert not response.context.get("form").is_valid()

        # Possible to submit a valid NIR and thus effect the changes
        valid_nir = "141068078200557"
        user = self._test_job_seeker_signup_forms(client, valid_nir)
        assert user.jobseeker_profile.nir == valid_nir

    def test_job_seeker_signup_temporary_nir_invalid_birthdate(self, client):
        nir = "1234567895GHTUI"

        job_seeker_data = JobSeekerFactory.build()
        post_data = {
            "nir": nir,
            "title": job_seeker_data.title,
            "first_name": job_seeker_data.first_name,
            "last_name": job_seeker_data.last_name,
            "email": job_seeker_data.email,
            "birthdate": "Invalid birthdate",
        }

        url = reverse("signup:job_seeker")
        response = client.post(url, post_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {
            "nir": ["Ce numéro n'est pas valide."],
            "birthdate": ["Saisissez une date valide."],
        }

        # Cannot skip the form by passing skip
        post_data["skip"] = 1
        response = client.post(url, post_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {
            "birthdate": ["Saisissez une date valide."],
        }

    def test_job_seeker_signup_with_existing_email(self, client):
        alice = JobSeekerFactory(email="alice@evil.com")
        url = reverse("signup:job_seeker")
        response = client.post(
            url,
            {
                "title": "MME",
                "first_name": "Alice",
                "last_name": "Evil",
                "email": "alice@evil.com",
                "birthdate": alice.jobseeker_profile.birthdate,
                "nir": "141068078200557",
            },
        )
        assert response.status_code == 200
        assert response.context["form"].errors == {
            "email": ["Un autre utilisateur utilise déjà cette adresse e-mail."]
        }

    def test_job_seeker_visit_credentials_without_session(self, client):
        assert client.session.get(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY) is None

        response = client.get(reverse("signup:job_seeker_credentials"))
        assertRedirects(response, reverse("signup:job_seeker"))

    def test_job_seeker_signup_weak_password(self, client, snapshot):
        url = reverse("signup:job_seeker")
        response = client.get(url)
        assert response.status_code == 200

        job_seeker_data = JobSeekerFactory.build(for_snapshot=True)
        post_data = {
            "nir": job_seeker_data.jobseeker_profile.nir,
            "title": job_seeker_data.title,
            "first_name": job_seeker_data.first_name,
            "last_name": job_seeker_data.last_name,
            "email": job_seeker_data.email,
            "birthdate": job_seeker_data.jobseeker_profile.birthdate,
        }

        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("signup:job_seeker_credentials"))
        assert client.session.get(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY)

        url = reverse("signup:job_seeker_credentials")
        response = client.get(url)
        assert response.status_code == 200

        post_data = {
            "password1": "weak_password",
            "password2": "weak_password",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {
            "password1": [
                "Ce mot de passe est trop court. Il doit contenir au minimum 14 caractères.",
                "Le mot de passe doit contenir au moins 3 des 4 types suivants : "
                "majuscules, minuscules, chiffres, caractères spéciaux.",
            ]
        }
        form = parse_response_to_soup(response, selector="form.js-prevent-multiple-submit")
        assert str(form) == snapshot

    @respx.mock
    @override_settings(
        FRANCE_CONNECT_BASE_URL="https://france.connect.fake",
        FRANCE_CONNECT_CLIENT_ID="IC_CLIENT_ID_123",
        FRANCE_CONNECT_CLIENT_SECRET="IC_CLIENT_SECRET_123",
    )
    @reload_module(fc_constants)
    def test_job_seeker_nir_with_france_connect(self, client):
        # NIR is set on a previous step and tested separately.
        # See self.test_job_seeker_signup
        nir = "141068078200557"
        job_seeker_data = JobSeekerFactory.build()
        post_data = {
            "nir": nir,
            "title": job_seeker_data.title,
            "first_name": job_seeker_data.first_name,
            "last_name": job_seeker_data.last_name,
            "email": job_seeker_data.email,
            "birthdate": job_seeker_data.jobseeker_profile.birthdate,
        }
        response = client.post(reverse("signup:job_seeker"), data=post_data)
        assertRedirects(response, reverse("signup:job_seeker_credentials"))

        assert client.session.get(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY)

        url = reverse("signup:job_seeker_credentials")
        response = client.get(url)
        fc_url = reverse("france_connect:authorize")
        assertContains(response, fc_url)

        # New created job seeker has no title and is redirected to complete its infos
        mock_oauth_dance(client, expected_route="dashboard:edit_user_info")
        job_seeker = User.objects.get(email=FC_USERINFO["email"])
        assert nir == job_seeker.jobseeker_profile.nir
        assert job_seeker.has_jobseeker_profile

        # The session key has been removed
        assert client.session.get(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY) is None

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

        nir = ""
        job_seeker_data = JobSeekerFactory.build()
        post_data = {
            "nir": nir,
            "title": job_seeker_data.title,
            "first_name": job_seeker_data.first_name,
            "last_name": job_seeker_data.last_name,
            "email": job_seeker_data.email,
            "birthdate": job_seeker_data.jobseeker_profile.birthdate,
            "skip": 1,
        }
        response = client.post(reverse("signup:job_seeker"), data=post_data)
        assertRedirects(response, reverse("signup:job_seeker_credentials"))

        assert client.session.get(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY)

        # Temporary NIR is not stored with user information.
        url = reverse("signup:job_seeker_credentials")
        response = client.get(url)
        fc_url = reverse("france_connect:authorize")
        assertContains(response, fc_url)

        # New created job seeker has no title and is redirected to complete its infos
        mock_oauth_dance(client, expected_route="dashboard:edit_user_info")
        job_seeker = User.objects.get(email=FC_USERINFO["email"])
        assert not job_seeker.jobseeker_profile.nir
        assert job_seeker.has_jobseeker_profile

    @pytest.mark.parametrize(
        "erroneous_fields,snapshot_name",
        [
            (["email"], "email_conflict"),
            (["email", "first_name", "last_name"], "email_and_name_conflict"),
            (["nir"], "nir_conflict"),
            (["email", "first_name", "last_name", "birthdate"], "missing_only_nir"),
            (["email", "nir", "first_name", "birthdate"], "missing_only_last_name"),
            (["email", "nir", "last_name", "birthdate"], "missing_only_first_name"),
            (["email", "nir", "first_name", "last_name"], "missing_only_birthdate"),
            (["nir", "first_name", "last_name", "birthdate"], "missing_only_email"),
            (["email", "nir", "first_name", "last_name", "birthdate"], "complete_match"),
            (["nir", "birthdate"], "nir_plus_mispelled_name"),
        ],
    )
    def test_job_seeker_signup_with_conflicting_fields(self, erroneous_fields, snapshot_name, client, snapshot):
        """
        Test registration error behaviour when key fields (NIR/email) conflict with existing user(s)
        A modal with detailed error information is displayed to the user
        """
        existing_user = JobSeekerFactory(for_snapshot=True)

        job_seeker_data = JobSeekerFactory.build()
        post_data = {
            "nir": job_seeker_data.jobseeker_profile.nir,
            "title": job_seeker_data.title,
            "first_name": job_seeker_data.first_name,
            "last_name": job_seeker_data.last_name,
            "email": job_seeker_data.email,
            "birthdate": str(job_seeker_data.jobseeker_profile.birthdate),
        }

        # Prepare conflict state directed by erroneous_fields parameter
        for erroneous_field in erroneous_fields:
            try:
                post_data[erroneous_field] = getattr(existing_user, erroneous_field)
            except AttributeError:
                post_data[erroneous_field] = getattr(existing_user.jobseeker_profile, erroneous_field)

        response = client.post(reverse("signup:job_seeker"), post_data)
        assert response.status_code == 200

        # Modal is rendered with expected error message according to the conflicting fields
        assertMessages(response, [messages.Message(messages.ERROR, snapshot(name=snapshot_name))])
        assert str(parse_response_to_soup(response, selector="#message-modal-1-label")) == snapshot(
            name=f"{snapshot_name}_title"
        )
        assertContains(response, reverse("login:existing_user", args=(existing_user.public_id,)))

        # NOTE: error is rendered for the case that the user ignores the modal
        if "email" in erroneous_fields:
            assert response.context["form"].errors["email"] == [
                "Un autre utilisateur utilise déjà cette adresse e-mail."
            ]
        if "jobseeker_profile__nir" in erroneous_fields:
            assert response.context["form"].errors["nir"] == ["Un compte avec ce numéro existe déjà."]

    def test_job_seeker_signup_with_conflicting_email_not_verified(self, client, snapshot):
        existing_user = JobSeekerFactory(for_snapshot=True)
        unverified_email_address = existing_user.emailaddress_set.create(email=existing_user.email, verified=False)

        job_seeker_data = JobSeekerFactory.build()
        post_data = {
            "nir": job_seeker_data.jobseeker_profile.nir,
            "title": job_seeker_data.title,
            "first_name": job_seeker_data.first_name,
            "last_name": job_seeker_data.last_name,
            "email": unverified_email_address.email,  # email conflict
            "birthdate": str(job_seeker_data.jobseeker_profile.birthdate),
        }

        response = client.post(reverse("signup:job_seeker"), post_data)
        assert response.status_code == 200

        # Modal is rendered with expected error message according to the conflicting fields
        assertMessages(response, [messages.Message(messages.ERROR, snapshot)])
        assert response.context["form"].errors["email"] == ["Un autre utilisateur utilise déjà cette adresse e-mail."]
        assertContains(response, reverse("login:existing_user", kwargs={"user_public_id": existing_user.public_id}))

    def test_job_seeker_signup_with_conflicting_email_temporary_nir(self, client, snapshot):
        existing_user = JobSeekerFactory(for_snapshot=True)

        post_data = {
            "nir": "1234567895GHTUI",
            "title": existing_user.title,
            "first_name": existing_user.first_name,
            "last_name": existing_user.last_name,
            "email": existing_user.email,  # email conflict
            "birthdate": str(existing_user.jobseeker_profile.birthdate),
            "skip": 1,
        }

        response = client.post(reverse("signup:job_seeker"), post_data)
        assert response.status_code == 200

        assertMessages(response, [messages.Message(messages.ERROR, snapshot)])
        assert response.context["form"].errors["email"] == ["Un autre utilisateur utilise déjà cette adresse e-mail."]
        assertContains(response, reverse("login:existing_user", kwargs={"user_public_id": existing_user.public_id}))

    def test_job_seeker_signup_birth_fields_conflict_temporary_nir(self, client, snapshot):
        existing_user = JobSeekerFactory(for_snapshot=True, jobseeker_profile__nir="")

        post_data = {
            "nir": "1234567895GHTUI",
            "title": existing_user.title,
            "first_name": existing_user.first_name,
            "last_name": existing_user.last_name,
            "email": "afreshemail@adomain.org",  # no email conflict
            "birthdate": str(existing_user.jobseeker_profile.birthdate),
            "skip": 1,
        }

        response = client.post(reverse("signup:job_seeker"), post_data, follow=True)

        # Non-blocking, the user can return to the signup process if it's not them
        assertRedirects(response, reverse("signup:job_seeker_credentials"))
        assertMessages(response, [messages.Message(messages.ERROR, snapshot)])
        assert str(parse_response_to_soup(response, selector="#message-modal-1-label")) == snapshot(
            name="birth_fields_conflict_title"
        )
        assertContains(response, reverse("login:existing_user", kwargs={"user_public_id": existing_user.public_id}))

    def test_job_seeker_signup_birth_fields_conflict_redefine_nir(self, client, snapshot):
        existing_user = JobSeekerFactory(for_snapshot=True, jobseeker_profile__nir="")

        post_data = {
            "nir": "141068078200557",
            "title": existing_user.title,
            "first_name": existing_user.first_name,
            "last_name": existing_user.last_name,
            "email": "afreshemail@adomain.org",  # no email conflict
            "birthdate": str(existing_user.jobseeker_profile.birthdate),
        }

        response = client.post(reverse("signup:job_seeker"), post_data, follow=True)

        # Non-blocking, the user can return to the signup process if it's not them
        assertRedirects(response, reverse("signup:job_seeker_credentials"))
        assertMessages(response, [messages.Message(messages.ERROR, snapshot)])
        assert str(parse_response_to_soup(response, selector="#message-modal-1-label")) == snapshot(
            name="birth_fields_conflict_title"
        )
        assertContains(response, reverse("login:existing_user", kwargs={"user_public_id": existing_user.public_id}))

    def test_job_seeker_signup_email_and_nir_priorities(self, client):
        """
        The NIR is normally a more reliable source of unicity than email
        When the NIR is undefined (e.g. temporary), then a matching email is more important
        """
        existing_user = JobSeekerFactory(jobseeker_profile__nir="")

        post_data = {
            "nir": "",
            "title": existing_user.title,
            "first_name": existing_user.first_name,
            "last_name": existing_user.last_name,
            "email": existing_user.email,
            "birthdate": existing_user.jobseeker_profile.birthdate,
            "skip": 1,
        }

        response = client.post(reverse("signup:job_seeker"), post_data)
        assert response.status_code == 200

        # Matching all information except the (temporary) NIR
        assert "Vous possédez déjà un compte" in str(
            parse_response_to_soup(response, selector="#message-modal-1-label")
        )
        assertContains(response, reverse("login:existing_user", args=(existing_user.public_id,)))

    # TODO(calum): temporary test relating to code migration, remove in the week following deployment
    def test_job_seeker_signup_temporary_redirects(self, client):
        response = client.get(reverse("signup:job_seeker_nir"))
        assertRedirects(response, reverse("signup:job_seeker_situation"))

        session = client.session
        session["job_seeker_nir"] = "141068078200557"
        session.save()

        response = client.get(reverse("signup:job_seeker"))
        assertRedirects(response, reverse("signup:job_seeker_situation"))

        session["job_seeker_nir"] = "141068078200557"
        session.save()
        response = client.get(reverse("signup:job_seeker_credentials"))
        assertRedirects(response, reverse("signup:job_seeker"))

        # Can continue with the process on the redirected page
        job_seeker_data = JobSeekerFactory.build()
        post_data = {
            "nir": "141068078200557",
            "title": job_seeker_data.title,
            "first_name": job_seeker_data.first_name,
            "last_name": job_seeker_data.last_name,
            "email": job_seeker_data.email,
            "birthdate": job_seeker_data.jobseeker_profile.birthdate,
        }

        response = client.post(response.url, data=post_data)
        assert client.session.get(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY)
        assertRedirects(response, reverse("signup:job_seeker_credentials"))
