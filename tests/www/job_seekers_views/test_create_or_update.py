import datetime
import uuid

import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from itou.asp.models import Commune, Country
from itou.users.enums import Title
from itou.utils.session import SessionNamespace
from itou.utils.urls import add_url_params
from itou.www.job_seekers_views.enums import JobSeekerSessionKinds
from tests.companies.factories import CompanyFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import KNOWN_SESSION_KEYS


class TestGetOrCreateForJobSeeker:
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


class TestGetOrCreateForSender:
    @pytest.mark.parametrize(
        "company_value, tunnel_value, from_url_value, expected_status_code",
        [
            # Valid parameters
            pytest.param("valid", "valid", "valid", 302, id="valid_values"),
            pytest.param("valid", "valid_hire", "valid", 302, id="valid_values_hire"),
            # Invalid parameters
            pytest.param(None, "valid", "valid", 404, id="missing_company"),
            pytest.param(None, "valid", "valid_hire", 404, id="missing_company_hire"),
            pytest.param("invalid", "valid", "valid", 404, id="invalid_company"),
            pytest.param("valid", "invalid", "valid", 404, id="invalid_tunnel"),
            pytest.param("valid", None, "valid", 404, id="missing_tunnel"),
            pytest.param("valid", "valid", None, 404, id="missing_from_url"),
        ],
    )
    def test_start_get_or_create_sender(
        self,
        company_value,
        tunnel_value,
        from_url_value,
        expected_status_code,
        client,
    ):
        job_seeker = JobSeekerFactory()
        company = CompanyFactory(with_membership=True)
        user = company.members.get()
        client.force_login(user)

        match company_value:
            case "valid":
                company_pk = company.pk
            case "invalid":
                company_pk = "invalid_pk"
            case _:
                company_pk = None

        match tunnel_value:
            case "valid":
                tunnel = "sender"
            case "valid_hire":
                tunnel = "hire"
            case "invalid":
                tunnel = "invalid-tunnel"
            case _:
                tunnel = None

        if from_url_value == "valid":
            from_url = reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        else:
            from_url = None

        params = {
            "tunnel": tunnel,
            "company": company_pk,
            "from_url": from_url,
        }
        start_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)

        response = client.get(start_url)
        assert response.status_code == expected_status_code

        if expected_status_code == 302:
            [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
            next_url = reverse(
                f"job_seekers_views:check_nir_for_{tunnel}",
                kwargs={"session_uuid": job_seeker_session_name},
            )

            assertRedirects(response, next_url)
            assert client.session[job_seeker_session_name].get("config").get("from_url") == from_url
            response = client.get(next_url)
            assertContains(
                response,
                f"""
                    <a href="{from_url}"
                    class="btn btn-link btn-ico ps-lg-0 w-100 w-lg-auto"
                    aria-label="Annuler la saisie de ce formulaire">
                      <i class="ri-close-line ri-lg" aria-hidden="true"></i>
                      <span>Annuler</span>
                    </a>
                """,
                html=True,
            )

    def test_check_nir_with_session(self, client):
        company = CompanyFactory(with_membership=True)
        client.force_login(company.members.get())

        # Init session
        start_url = reverse("apply:start", kwargs={"company_pk": company.pk})
        client.get(start_url, follow=True)
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
        client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), follow=True)
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
        client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), follow=True)
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
        client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), follow=True)
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


class TestUpdateForJobSeeker:
    def test_start_update_job_seeker_forbidden(self, client):
        job_seeker = JobSeekerFactory(jobseeker_profile__birthdate=None, jobseeker_profile__nir="")
        company = CompanyFactory(with_membership=True)
        client.force_login(job_seeker)

        company_pk = company.pk

        from_url = reverse(
            "apply:application_jobs",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        params = {
            "job_seeker": job_seeker.public_id,
            "company": company_pk,
            "from_url": from_url,
        }
        start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)

        response = client.get(start_url)
        assert response.status_code == 403


class TestUpdateForSender:
    @pytest.mark.parametrize(
        "job_seeker_value, from_url_value, expected_status_code",
        [
            # Valid parameters
            pytest.param("valid", "valid", 302, id="valid_values"),
            # Invalid parameters
            pytest.param("invalid_uuid", "valid", 404, id="invalid_job_seeker_not_a_uuid"),
            pytest.param("invalid", "valid", 404, id="invalid_job_seeker_not_found"),
            pytest.param(None, "valid", 404, id="missing_job_seeker"),
            pytest.param("valid", None, 404, id="missing_from_url"),
        ],
    )
    def test_start_update(self, job_seeker_value, from_url_value, expected_status_code, client):
        job_seeker = JobSeekerFactory()
        company = CompanyFactory(with_membership=True)
        user = company.members.get()
        client.force_login(user)

        match job_seeker_value:
            case "valid":
                job_seeker_public_id = job_seeker.public_id
            case "invalid_uuid":
                job_seeker_public_id = "invalid_uuid_value"
            case "invalid":
                job_seeker_public_id = uuid.uuid4()
            case _:
                job_seeker_public_id = None

        if from_url_value == "valid":
            from_url = reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        else:
            from_url = None

        params = {
            "job_seeker": job_seeker_public_id,
            "from_url": from_url,
        }
        start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)

        response = client.get(start_url)
        assert response.status_code == expected_status_code

        if expected_status_code == 302:
            [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
            step_1_url = reverse(
                "job_seekers_views:update_job_seeker_step_1",
                kwargs={"session_uuid": job_seeker_session_name},
            )

            assertRedirects(response, step_1_url)
            assert client.session[job_seeker_session_name].get("config").get("from_url") == from_url
            response = client.get(step_1_url)
            assertContains(
                response,
                f"""
                    <a href="{from_url}"
                    class="btn btn-link btn-ico ps-lg-0 w-100 w-lg-auto"
                    aria-label="Annuler la saisie de ce formulaire">
                      <i class="ri-close-line ri-lg" aria-hidden="true"></i>
                      <span>Annuler</span>
                    </a>
                """,
                html=True,
            )

    def test_update_with_wrong_session(self, client):
        job_seeker = JobSeekerFactory()
        company = CompanyFactory(with_membership=True)
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        client.force_login(prescriber)

        # Create a session with a wrong tunnel key
        job_seeker_session = SessionNamespace.create_uuid_namespace(
            client.session,
            data={
                "config": {
                    "from_url": reverse("dashboard:index"),
                    "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
                },
                "job_seeker_pk": job_seeker.pk,
                "apply": {"company_pk": company.pk},
            },
        )
        job_seeker_session.save()

        url = reverse("job_seekers_views:update_job_seeker_step_1", kwargs={"session_uuid": job_seeker_session.name})
        response = client.get(url)

        assert response.status_code == 404

    @pytest.mark.parametrize(
        "born_in_france", [pytest.param(True, id="born_in_france"), pytest.param(False, id="born_outside_france")]
    )
    def test_update_step_1(self, born_in_france, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.get()
        job_seeker = JobSeekerFactory(created_by=user, title=Title.M, jobseeker_profile__nir="111116411111144")
        client.force_login(user)

        # Init session
        params = {
            "job_seeker": job_seeker.public_id,
            "from_url": reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        }
        start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)
        client.get(start_url)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]

        birthdate = datetime.date(1911, 11, 1)
        response = client.post(
            reverse(
                "job_seekers_views:update_job_seeker_step_1",
                kwargs={"session_uuid": job_seeker_session_name},
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
                kwargs={"session_uuid": job_seeker_session_name},
            ),
        )

    def test_birth_country_not_france_and_birthplace(self, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.get()
        job_seeker = JobSeekerFactory(created_by=user, title=Title.M, jobseeker_profile__nir="111116411111144")
        client.force_login(user)

        # Init session
        params = {
            "job_seeker": job_seeker.public_id,
            "from_url": reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        }
        start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)
        client.get(start_url)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]

        birthdate = datetime.date(1911, 11, 1)
        response = client.post(
            reverse(
                "job_seekers_views:update_job_seeker_step_1",
                kwargs={"session_uuid": job_seeker_session_name},
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

        # Init session
        params = {
            "job_seeker": job_seeker.public_id,
            "from_url": reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        }
        start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)
        client.get(start_url)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]

        response = client.post(
            reverse(
                "job_seekers_views:update_job_seeker_step_1",
                kwargs={"session_uuid": job_seeker_session_name},
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
