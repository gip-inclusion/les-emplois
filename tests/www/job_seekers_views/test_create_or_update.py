import datetime
import uuid

import pytest
from django.contrib import messages
from django.template.defaultfilters import urlencode
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertRedirects

from itou.asp.models import Commune, Country, RSAAllocation
from itou.gps.models import FollowUpGroupMembership
from itou.users.enums import LackOfPoleEmploiId, Title
from itou.users.models import JobSeekerProfile, User
from itou.utils.mocks.address_format import mock_get_geocoding_data_by_ban_api_resolved
from itou.utils.session import SessionNamespace
from itou.utils.urls import add_url_params
from itou.www.job_seekers_views.enums import JobSeekerSessionKinds
from tests.cities.factories import create_city_geispolsheim, create_test_cities
from tests.companies.factories import CompanyFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import (
    PrescriberOrganizationWith2MembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from tests.users.factories import ItouStaffFactory, JobSeekerFactory
from tests.utils.test import parse_response_to_soup, session_data_without_known_keys
from tests.www.apply.test_submit import CONFIRM_RESET_MARKUP, LINK_RESET_MARKUP


class TestGetOrCreateAsOther:
    TUNNELS = ["sender", "hire", "gps"]

    def test_labor_inspectors_are_not_allowed_to_get_or_create_job_seeker(self, client):
        company = CompanyFactory()
        institution_member = InstitutionMembershipFactory().user

        client.force_login(institution_member)

        for tunnel in self.TUNNELS:
            params = {
                "tunnel": tunnel,
                "company": company.pk,
                "from_url": reverse("companies_views:card", kwargs={"siae_id": company.pk}),
            }
            start_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
            response = client.get(start_url)
            assert response.status_code == 403

    def test_itou_staff_are_not_allowed_to_get_or_create_job_seeker(self, client):
        company = CompanyFactory()
        user = ItouStaffFactory()

        client.force_login(user)

        for tunnel in self.TUNNELS:
            params = {
                "tunnel": tunnel,
                "company": company.pk,
                "from_url": reverse("companies_views:card", kwargs={"siae_id": company.pk}),
            }
            start_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
            response = client.get(start_url)
            assert response.status_code == 403

    def test_anonymous_access(self, client):
        company = CompanyFactory()

        for tunnel in self.TUNNELS:
            params = {
                "tunnel": tunnel,
                "company": company.pk,
                "from_url": reverse("companies_views:card", kwargs={"siae_id": company.pk}),
            }
            start_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
            response = client.get(start_url)
            assertRedirects(response, reverse("account_login") + f"?next={urlencode(start_url)}")


class TestGetOrCreateForJobSeeker:
    def test_start_create_forbidden_for_job_seekers(self, client):
        TUNNELS = ["sender", "hire", "gps"]
        company = CompanyFactory()
        job_seeker = JobSeekerFactory()

        client.force_login(job_seeker)

        for tunnel in TUNNELS:
            params = {
                "tunnel": tunnel,
                "company": company.pk,
                "from_url": reverse("companies_views:card", kwargs={"siae_id": company.pk}),
            }
            start_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
            response = client.get(start_url)
            assert response.status_code == 403

    def test_create_forbidden_for_job_seekers(self, client):
        TUNNELS = ["sender", "hire", "gps"]
        company = CompanyFactory()
        job_seeker = JobSeekerFactory()

        client.force_login(job_seeker)

        for tunnel in TUNNELS:
            # Init session, since a job seeker cannot access the start view this should be impossible
            session = client.session
            session_name = str(uuid.uuid4())
            session[session_name] = {
                "config": {
                    "tunnel": tunnel,
                    "from_url": reverse("companies_views:card", kwargs={"siae_id": company.pk}),
                },
                "apply": {"company_pk": company.pk},
            }
            session.save()
            response = client.get(
                reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": session_name})
            )
            assert response.status_code == 403

            response = client.get(
                reverse("job_seekers_views:check_nir_for_hire", kwargs={"session_uuid": session_name})
            )
            assert response.status_code == 403

    def test_check_nir_with_session(self, client):
        company = CompanyFactory(with_membership=True)
        user = JobSeekerFactory(jobseeker_profile__birthdate=None, jobseeker_profile__nir="")
        reset_url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        client.force_login(user)

        # Init session
        start_url = reverse("apply:start", kwargs={"company_pk": company.pk})
        client.get(start_url, {"back_url": reset_url})
        [job_seeker_session_name] = [
            k for k in session_data_without_known_keys(client.session) if not k.startswith("job_application")
        ]

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
        [job_seeker_session_name] = [
            k for k in session_data_without_known_keys(client.session) if not k.startswith("job_application")
        ]

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
            pytest.param(None, "valid_standalone", "valid", 302, id="valid_values_standalone"),
            pytest.param("valid", "valid_standalone", "valid", 302, id="valid_values_standalone"),
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
            case "valid_standalone":
                tunnel = "standalone"
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
            [job_seeker_session_name] = session_data_without_known_keys(client.session)
            view_name = (
                "job_seekers_views:check_nir_for_hire"
                if tunnel == "hire"
                else "job_seekers_views:check_nir_for_sender"
            )
            next_url = reverse(
                view_name,
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

    def test_check_nir_for_jobseeker_forbidden_for_sender(self, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.get()
        client.force_login(user)

        # Init a job_seeker session for a sender (should be impossible, the tunnels
        # are well separated in apply StartView)
        session = client.session
        session_name = str(uuid.uuid4())
        session[session_name] = {
            "config": {
                "from_url": reverse("companies_views:card", kwargs={"siae_id": company.pk}),
            },
            "apply": {"company_pk": company.pk},
        }
        session.save()
        response = client.get(
            reverse("job_seekers_views:check_nir_for_job_seeker", kwargs={"session_uuid": session_name})
        )
        assert response.status_code == 403

    def test_check_nir_with_session(self, client):
        company = CompanyFactory(with_membership=True)
        client.force_login(company.members.get())

        # Init session
        start_url = reverse("apply:start", kwargs={"company_pk": company.pk})
        client.get(start_url, follow=True)
        [job_seeker_session_name] = [
            k for k in session_data_without_known_keys(client.session) if not k.startswith("job_application")
        ]

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
        [job_seeker_session_name] = [
            k for k in session_data_without_known_keys(client.session) if not k.startswith("job_application")
        ]

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
        [job_seeker_session_name] = [
            k for k in session_data_without_known_keys(client.session) if not k.startswith("job_application")
        ]

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
        [job_seeker_session_name] = [
            k for k in session_data_without_known_keys(client.session) if not k.startswith("job_application")
        ]

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


class TestStandaloneCreateAsPrescriber:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        [self.city] = create_test_cities(["67"], num_per_department=1)
        settings.API_BAN_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

    @freeze_time("2024-08-30")
    @pytest.mark.parametrize("case", ["not_in_list", "in_list_user", "in_list_organization", "in_list_application"])
    def test_standalone_creation_as_prescriber_existing_nir(self, client, snapshot, case):
        from_url = reverse("job_seekers_views:list")
        prescriber_organization = PrescriberOrganizationWith2MembershipFactory(authorized=True)
        other_organization = PrescriberOrganizationWithMembershipFactory()
        user = prescriber_organization.members.first()
        other_user = prescriber_organization.members.last()
        other_user_in_other_organization = other_organization.members.first()
        client.force_login(user)

        existing_job_seeker = JobSeekerFactory(for_snapshot=True)

        match case:
            case "in_list_user":
                existing_job_seeker.created_by = user
                next_url = add_url_params(
                    reverse(
                        "search:employers_results",
                    ),
                    {"job_seeker_public_id": existing_job_seeker.public_id, "city": existing_job_seeker.city_slug},
                )
            case "in_list_organization":
                existing_job_seeker.created_by = other_user
                existing_job_seeker.jobseeker_profile.created_by_prescriber_organization = prescriber_organization
                next_url = add_url_params(
                    reverse(
                        "search:employers_results",
                    ),
                    {"job_seeker_public_id": existing_job_seeker.public_id, "city": existing_job_seeker.city_slug},
                )
            case "in_list_application":
                existing_job_seeker.created_by = other_user_in_other_organization
                existing_job_seeker.jobseeker_profile.created_by_prescriber_organization = None
                next_url = add_url_params(
                    reverse(
                        "search:employers_results",
                    ),
                    {"job_seeker_public_id": existing_job_seeker.public_id, "city": existing_job_seeker.city_slug},
                )
                JobApplicationFactory(
                    job_seeker=existing_job_seeker,
                    sender=user,
                    sender_prescriber_organization=None,
                    updated_at=timezone.now() - datetime.timedelta(days=1),
                )
            case _:
                # Not in list
                existing_job_seeker.created_by = other_user_in_other_organization
                existing_job_seeker.jobseeker_profile.created_by_prescriber_organization = other_organization
                next_url = reverse(
                    "job_seekers_views:details",
                    kwargs={"public_id": existing_job_seeker.public_id},
                )
        existing_job_seeker.save()
        existing_job_seeker.jobseeker_profile.save()

        # Entry point.
        # ----------------------------------------------------------------------

        params = {"tunnel": "standalone", "from_url": from_url}
        start_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
        client.get(start_url)
        [job_seeker_session_name] = session_data_without_known_keys(client.session)
        check_nir_url = reverse(
            "job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name}
        )

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = client.post(check_nir_url, data={"nir": existing_job_seeker.jobseeker_profile.nir, "preview": 1})
        modal = parse_response_to_soup(response, selector="#nir-confirmation-modal")
        assert str(modal) == snapshot()

        response = client.post(check_nir_url, data={"nir": existing_job_seeker.jobseeker_profile.nir, "confirm": 1})
        assertRedirects(response, next_url)

    @freeze_time("2024-08-30")
    @pytest.mark.parametrize("case", ["not_in_list", "in_list_user", "in_list_organization", "in_list_application"])
    def test_standalone_creation_as_prescriber_existing_email(self, client, snapshot, case):
        from_url = reverse("job_seekers_views:list")
        prescriber_organization = PrescriberOrganizationWith2MembershipFactory(authorized=True)
        other_organization = PrescriberOrganizationWithMembershipFactory()
        user = prescriber_organization.members.first()
        other_user = prescriber_organization.members.last()
        other_user_in_other_organization = other_organization.members.first()
        client.force_login(user)

        existing_job_seeker = JobSeekerFactory(for_snapshot=True)

        match case:
            case "in_list_user":
                existing_job_seeker.created_by = user
                next_url = add_url_params(
                    reverse(
                        "search:employers_results",
                    ),
                    {"job_seeker_public_id": existing_job_seeker.public_id, "city": existing_job_seeker.city_slug},
                )
            case "in_list_organization":
                existing_job_seeker.created_by = other_user
                existing_job_seeker.jobseeker_profile.created_by_prescriber_organization = prescriber_organization
                next_url = add_url_params(
                    reverse(
                        "search:employers_results",
                    ),
                    {"job_seeker_public_id": existing_job_seeker.public_id, "city": existing_job_seeker.city_slug},
                )
            case "in_list_application":
                existing_job_seeker.created_by = other_user_in_other_organization
                existing_job_seeker.jobseeker_profile.created_by_prescriber_organization = None
                next_url = add_url_params(
                    reverse(
                        "search:employers_results",
                    ),
                    {"job_seeker_public_id": existing_job_seeker.public_id, "city": existing_job_seeker.city_slug},
                )
                JobApplicationFactory(
                    job_seeker=existing_job_seeker,
                    sender=user,
                    sender_prescriber_organization=None,
                    updated_at=timezone.now() - datetime.timedelta(days=1),
                )
            case _:
                # Not in list
                existing_job_seeker.created_by = other_user_in_other_organization
                existing_job_seeker.jobseeker_profile.created_by_prescriber_organization = other_organization
                next_url = reverse(
                    "job_seekers_views:details",
                    kwargs={"public_id": existing_job_seeker.public_id},
                )
        existing_job_seeker.save()
        existing_job_seeker.jobseeker_profile.save()

        # Entry point.
        # ----------------------------------------------------------------------

        params = {"tunnel": "standalone", "from_url": from_url}
        start_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
        client.get(start_url)
        [job_seeker_session_name] = session_data_without_known_keys(client.session)
        search_by_email_url = reverse(
            "job_seekers_views:search_by_email_for_sender", kwargs={"session_uuid": job_seeker_session_name}
        )

        # Step determine the job seeker with an email (skipping the NIR)
        # ----------------------------------------------------------------------

        response = client.post(search_by_email_url, data={"email": existing_job_seeker.email, "preview": 1})
        modal = parse_response_to_soup(response, selector="#email-confirmation-modal")
        assert str(modal) == snapshot()

        response = client.post(search_by_email_url, data={"email": existing_job_seeker.email, "confirm": 1})
        assertRedirects(response, next_url)

    def test_standalone_creation_as_prescriber(self, client):
        from_url = reverse("job_seekers_views:list")
        user = PrescriberOrganizationWithMembershipFactory().members.first()
        client.force_login(user)

        dummy_job_seeker = JobSeekerFactory.build(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="178122978200508",
            jobseeker_profile__birthdate=datetime.date(1978, 12, 20),
            title="M",
        )

        # Entry point.
        # ----------------------------------------------------------------------

        params = {"tunnel": "standalone", "from_url": from_url}
        start_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
        client.get(start_url)
        [job_seeker_session_name] = session_data_without_known_keys(client.session)
        next_url = reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name})

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % from_url)

        response = client.post(next_url, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "confirm": 1})

        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        expected_job_seeker_session = {
            "config": {
                "tunnel": "standalone",
                "from_url": from_url,
            },
            "profile": {"nir": dummy_job_seeker.jobseeker_profile.nir},
        }

        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % from_url)

        response = client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})

        expected_job_seeker_session |= {
            "user": {
                "email": dummy_job_seeker.email,
            },
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_1_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        # The NIR is prefilled
        assertContains(response, dummy_job_seeker.jobseeker_profile.nir)
        # Check that the back url is correct
        assertContains(
            response,
            reverse(
                "job_seekers_views:search_by_email_for_sender",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
        )
        assertContains(response, CONFIRM_RESET_MARKUP % from_url)

        geispolsheim = create_city_geispolsheim()
        birthdate = dummy_job_seeker.jobseeker_profile.birthdate

        # Let's check for consistency between the NIR, the birthdate and the title.
        # ----------------------------------------------------------------------

        post_data = {
            "title": "MME",  # inconsistent title
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = client.post(next_url, data=post_data)
        assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_TITLE % "")

        post_data = {
            "title": "M",
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": datetime.date(1978, 11, 20),  # inconsistent birthdate
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = client.post(next_url, data=post_data)
        assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_BIRTHDATE % "")

        # Resume to valid data and proceed with "normal" flow.
        # ----------------------------------------------------------------------

        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
            "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
            "birth_country": Country.france_id,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"]["birthdate"] = post_data.pop("birthdate")
        expected_job_seeker_session["profile"]["lack_of_nir_reason"] = post_data.pop("lack_of_nir_reason")
        expected_job_seeker_session["profile"]["birth_place"] = post_data.pop("birth_place")
        expected_job_seeker_session["profile"]["birth_country"] = post_data.pop("birth_country")
        expected_job_seeker_session["user"] |= post_data
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_2_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % from_url)

        post_data = {
            "ban_api_resolved_address": dummy_job_seeker.geocoding_address,
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": self.city.post_codes[0],
            "insee_code": self.city.code_insee,
            "city": self.city.name,
            "phone": dummy_job_seeker.phone,
            "fill_mode": "ban_api",
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["user"] |= post_data | {"address_line_2": "", "address_for_autocomplete": None}
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_3_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % from_url)

        post_data = {
            "education_level": dummy_job_seeker.jobseeker_profile.education_level,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"] |= post_data | {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED.value,
            "resourceless": False,
            "rqth_employee": False,
            "oeth_employee": False,
            "pole_emploi": False,
            "pole_emploi_id_forgotten": "",
            "pole_emploi_since": "",
            "unemployed": False,
            "unemployed_since": "",
            "rsa_allocation": False,
            "has_rsa_allocation": RSAAllocation.NO.value,
            "rsa_allocation_since": "",
            "ass_allocation": False,
            "ass_allocation_since": "",
            "aah_allocation": False,
            "aah_allocation_since": "",
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_end_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, "Créer le compte candidat")

        response = client.post(next_url)
        assert job_seeker_session_name not in client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)
        assert (
            new_job_seeker.jobseeker_profile.created_by_prescriber_organization
            == user.prescriberorganization_set.first()
        )
        next_url = reverse(
            "job_seekers_views:details",
            kwargs={"public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.SUCCESS,
                    f"Le compte du candidat {new_job_seeker.get_full_name()} a "
                    "bien été créé et ajouté à votre liste de candidats.",
                )
            ],
        )

        assert FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=new_job_seeker, member=user
        ).exists()


class TestUpdateAsOther:
    def test_labor_inspectors_are_not_allowed_update_job_seeker(self, client):
        institution_member = InstitutionMembershipFactory().user
        job_seeker = JobSeekerFactory()

        client.force_login(institution_member)

        params = {
            "job_seeker_public_id": job_seeker.public_id,
            "from_url": reverse("dashboard:index"),
        }
        start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)
        response = client.get(start_url)
        assert response.status_code == 403

    def test_itou_staff_are_not_allowed_to_update_job_seeker(self, client):
        user = ItouStaffFactory()
        job_seeker = JobSeekerFactory()

        client.force_login(user)

        params = {
            "job_seeker_public_id": job_seeker.public_id,
            "from_url": reverse("dashboard:index"),
        }
        start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)
        response = client.get(start_url)
        assert response.status_code == 403

    def test_anonymous_access(self, client):
        job_seeker = JobSeekerFactory()

        params = {
            "job_seeker_public_id": job_seeker.public_id,
            "from_url": reverse("dashboard:index"),
        }
        start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)
        response = client.get(start_url)
        assertRedirects(response, reverse("account_login") + f"?next={urlencode(start_url)}")


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
            "job_seeker_public_id": job_seeker.public_id,
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
            "job_seeker_public_id": job_seeker_public_id,
            "from_url": from_url,
        }
        start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)

        response = client.get(start_url)
        assert response.status_code == expected_status_code

        if expected_status_code == 302:
            [job_seeker_session_name] = session_data_without_known_keys(client.session)
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
            JobSeekerSessionKinds.GET_OR_CREATE,
            data={
                "config": {
                    "from_url": reverse("dashboard:index"),
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
            "job_seeker_public_id": job_seeker.public_id,
            "from_url": reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        }
        start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)
        client.get(start_url)
        [job_seeker_session_name] = session_data_without_known_keys(client.session)

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
            "job_seeker_public_id": job_seeker.public_id,
            "from_url": reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        }
        start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)
        client.get(start_url)
        [job_seeker_session_name] = session_data_without_known_keys(client.session)

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
            "job_seeker_public_id": job_seeker.public_id,
            "from_url": reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        }
        start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)
        client.get(start_url)
        [job_seeker_session_name] = session_data_without_known_keys(client.session)

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
