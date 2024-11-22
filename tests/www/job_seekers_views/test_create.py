import datetime

import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from tests.companies.factories import CompanyFactory
from tests.users.factories import (
    JobSeekerFactory,
    PrescriberFactory,
)
from tests.utils.test import KNOWN_SESSION_KEYS


class TestCreateForJobSeeker:
    def test_check_nir_with_session(self, client):
        company = CompanyFactory(with_membership=True)
        user = JobSeekerFactory(jobseeker_profile__birthdate=None, jobseeker_profile__nir="")
        reset_url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        client.force_login(user)

        # Init session
        start_url = reverse("apply:start", kwargs={"company_pk": company.pk})
        client.get(start_url)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]

        response = client.get(
            reverse("job_seekers_views:check_nir_for_job_seeker", kwargs={"session_uuid": job_seeker_session_name})
        )

        assertContains(response, company.display_name)
        assertContains(
            response,
            f"""
        <a href="{reset_url}" class="btn btn-link btn-ico ps-lg-0 w-100 w-lg-auto"
           aria-label="Annuler la saisie de ce formulaire">
            <i class="ri-close-line ri-lg" aria-hidden="true"></i>
            <span>Annuler</span>
        </a>""",
            html=True,
        )

    def test_cannot_check_nir_if_already_set(self, client):
        company = CompanyFactory(with_membership=True)
        user = JobSeekerFactory(
            jobseeker_profile__birthdate=datetime.date(1994, 2, 22), jobseeker_profile__nir="194022734304328"
        )
        client.force_login(user)

        # Init session
        start_url = reverse("apply:start", kwargs={"company_pk": company.pk})
        client.get(start_url)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]

        response = client.get(
            reverse("job_seekers_views:check_nir_for_job_seeker", kwargs={"session_uuid": job_seeker_session_name})
        )
        assertRedirects(
            response,
            reverse(
                "job_seekers_views:check_job_seeker_info",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": user.public_id},
            ),
        )


class TestCreateForSender:
    def test_check_nir_with_session(self, client):
        company = CompanyFactory(with_membership=True)
        user = JobSeekerFactory(jobseeker_profile__birthdate=None, jobseeker_profile__nir="")
        client.force_login(user)

        # Init session
        start_url = reverse("apply:start", kwargs={"company_pk": company.pk})
        client.get(start_url)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]

        response = client.get(
            reverse("job_seekers_views:check_nir_for_job_seeker", kwargs={"session_uuid": job_seeker_session_name})
        )

        assertContains(response, company.display_name)

    # TODO(ewen): to be removed after migration is complete
    @pytest.mark.ignore_unknown_variable_template_error(
        "job_seeker", "update_job_seeker", "readonly_form", "confirmation_needed"
    )
    def test_company_in_searchbyemail_after_deprecated_checknir(self, client):
        company = CompanyFactory(with_membership=True)
        user = PrescriberFactory(membership=True)
        client.force_login(user)

        # Check NIR.
        # ----------------------------------------------------------------------
        deprecated_checknir_url = reverse("job_seekers_views:check_nir_for_sender", kwargs={"company_pk": company.pk})
        nir = "141068078200557"
        post_data = {"nir": nir, "confirm": 1}
        response = client.post(deprecated_checknir_url, data=post_data)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        deprecated_email_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "profile": {
                "nir": nir,
            },
        }

        assert response.url == deprecated_email_url
        assert client.session[job_seeker_session_name] == expected_job_seeker_session
        assertRedirects(response, deprecated_email_url)

        # Search by email
        # ----------------------------------------------------------------------
        response = client.get(deprecated_email_url)
        new_checknir_url = reverse(
            "job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name}
        )
        expected_job_seeker_session |= {"profile": {"nir": nir}, "apply": {"company_pk": company.pk}}
        assertContains(response, f"<h3>{company.display_name}</h3>", html=True)
        assertContains(
            response,
            f"""<a href="{new_checknir_url}"
                class="btn btn-block btn-outline-primary"
                aria-label="Retourner à l’étape précédente">
                    <span>Retour</span>
                </a>""",
            html=True,
        )
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        email = "jean_dujardain@email.com"
        post_data = {"email": email, "confirm": 1}
        response = client.post(deprecated_email_url, data=post_data)
        deprecated_create_url = reverse(
            "job_seekers_views:create_job_seeker_step_1_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session |= {"user": {"email": email}}

        assert response.url == deprecated_create_url
        assert client.session[job_seeker_session_name] == expected_job_seeker_session
        assertRedirects(response, deprecated_create_url)

        # Create job seeker step 1.
        # ----------------------------------------------------------------------
        response = client.get(deprecated_create_url)
        new_email_url = reverse(
            "job_seekers_views:search_by_email_for_sender", kwargs={"session_uuid": job_seeker_session_name}
        )
        assert response.status_code == 200
        assertContains(
            response,
            f"""<a href="{new_email_url}"
                class="btn btn-block btn-outline-primary"
                aria-label="Retourner à l’étape précédente">
                    <span>Retour</span>
                </a>""",
            html=True,
        )
