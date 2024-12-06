import datetime

import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from itou.asp.models import Commune, Country
from itou.users.enums import Title
from tests.companies.factories import CompanyFactory
from tests.users.factories import (
    JobSeekerFactory,
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
        client.force_login(company.members.get())

        # Init session
        start_url = reverse("apply:start", kwargs={"company_pk": company.pk})
        client.get(start_url)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]

        response = client.get(
            reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name})
        )

        assertContains(response, company.display_name)

    @pytest.mark.parametrize(
        "born_in_france", [pytest.param(True, id="born_in_france"), pytest.param(False, id="born_outside_france")]
    )
    def test_create_step_1(self, born_in_france, client):
        company = CompanyFactory(with_membership=True)
        client.force_login(company.members.get())

        # Init session
        client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]

        birthdate = datetime.date(1911, 11, 1)
        response = client.post(
            reverse(
                "job_seekers_views:create_job_seeker_step_1_for_sender",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
            {
                "title": Title.M,
                "first_name": "Manuel",
                "last_name": "Calavera",
                "nir": "111116411111144",
                "birthdate": birthdate.isoformat(),
                **(
                    {
                        "birth_place": Commune.objects.by_insee_code_and_period("64483", birthdate).pk,
                        "birth_country": Country.objects.get(code=Country.INSEE_CODE_FRANCE).pk,
                    }
                    if born_in_france
                    else {"birth_country": Country.objects.exclude(code=Country.INSEE_CODE_FRANCE).first().pk}
                ),
            },
        )
        assertRedirects(
            response,
            reverse(
                "job_seekers_views:create_job_seeker_step_2_for_sender",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
        )

    def test_birth_country_not_france_and_birthplace(self, client):
        company = CompanyFactory(with_membership=True)
        client.force_login(company.members.get())

        # Init session
        client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]

        birthdate = datetime.date(1911, 11, 1)
        response = client.post(
            reverse(
                "job_seekers_views:create_job_seeker_step_1_for_sender",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
            {
                "title": Title.M,
                "first_name": "Manuel",
                "last_name": "Calavera",
                "nir": "111116411111144",
                "birthdate": birthdate.isoformat(),
                "birth_place": Commune.objects.by_insee_code_and_period("64483", birthdate).pk,
                "birth_country": Country.objects.exclude(code=Country.INSEE_CODE_FRANCE).order_by("?").first().pk,
            },
        )
        assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert">
                Il n'est pas possible de saisir une commune de naissance hors de France.
            </div>""",
            html=True,
            count=1,
        )

    def test_birth_country_france_and_no_birthplace(self, client):
        company = CompanyFactory(with_membership=True)
        client.force_login(company.members.get())

        # Init session
        client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]

        response = client.post(
            reverse(
                "job_seekers_views:create_job_seeker_step_1_for_sender",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
            {
                "title": Title.M,
                "first_name": "Manuel",
                "last_name": "Calavera",
                "nir": "111111111111120",
                "birthdate": "1911-11-01",
                # No birth_place
                "birth_country": Country.objects.get(code=Country.INSEE_CODE_FRANCE).pk,
            },
        )
        assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert">
            Si le pays de naissance est la France, la commune de naissance est obligatoire.
            </div>""",
            html=True,
            count=1,
        )


class TestUpdateJobSeekerStep1:
    @pytest.mark.parametrize(
        "born_in_france", [pytest.param(True, id="born_in_france"), pytest.param(False, id="born_outside_france")]
    )
    def test_create_step_1(self, born_in_france, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.get()
        job_seeker = JobSeekerFactory(created_by=user, title=Title.M, jobseeker_profile__nir="111116411111144")
        client.force_login(user)

        birthdate = datetime.date(1911, 11, 1)
        response = client.post(
            reverse(
                "job_seekers_views:update_job_seeker_step_1",
                kwargs={"job_seeker_public_id": job_seeker.public_id, "company_pk": company.pk},
            ),
            {
                "title": Title.M,
                "first_name": "Manuel",
                "last_name": "Calavera",
                "birthdate": birthdate.isoformat(),
                **(
                    {
                        "birth_place": Commune.objects.by_insee_code_and_period("64483", birthdate).pk,
                        "birth_country": Country.objects.get(code=Country.INSEE_CODE_FRANCE).pk,
                    }
                    if born_in_france
                    else {"birth_country": Country.objects.exclude(code=Country.INSEE_CODE_FRANCE).first().pk}
                ),
            },
        )
        assertRedirects(
            response,
            reverse(
                "job_seekers_views:update_job_seeker_step_2",
                kwargs={"job_seeker_public_id": job_seeker.public_id, "company_pk": company.pk},
            ),
        )

    def test_birth_country_not_france_and_birthplace(self, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.get()
        job_seeker = JobSeekerFactory(created_by=user, title=Title.M, jobseeker_profile__nir="111116411111144")
        client.force_login(user)

        birthdate = datetime.date(1911, 11, 1)
        response = client.post(
            reverse(
                "job_seekers_views:update_job_seeker_step_1",
                kwargs={"job_seeker_public_id": job_seeker.public_id, "company_pk": company.pk},
            ),
            {
                "title": Title.M,
                "first_name": "Manuel",
                "last_name": "Calavera",
                "birthdate": birthdate.isoformat(),
                "birth_place": Commune.objects.by_insee_code_and_period("64483", birthdate).pk,
                "birth_country": Country.objects.exclude(code=Country.INSEE_CODE_FRANCE).order_by("?").first().pk,
            },
        )
        assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert">
            Il n'est pas possible de saisir une commune de naissance hors de France.
            </div>""",
            html=True,
            count=1,
        )

    def test_birth_country_france_and_no_birthplace(self, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.get()
        job_seeker = JobSeekerFactory(created_by=user, title=Title.M, jobseeker_profile__nir="111116411111144")
        client.force_login(user)

        response = client.post(
            reverse(
                "job_seekers_views:update_job_seeker_step_1",
                kwargs={"job_seeker_public_id": job_seeker.public_id, "company_pk": company.pk},
            ),
            {
                "title": Title.M,
                "first_name": "Manuel",
                "last_name": "Calavera",
                "birthdate": "1911-11-01",
                # No birth_place
                "birth_country": Country.objects.get(code=Country.INSEE_CODE_FRANCE).pk,
            },
        )
        assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert">
            Si le pays de naissance est la France, la commune de naissance est obligatoire.
            </div>""",
            html=True,
            count=1,
        )
