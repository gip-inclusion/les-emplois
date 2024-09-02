import factory
import pytest
from django.urls import reverse_lazy
from pytest_django.asserts import assertNumQueries

from tests.asp.factories import CommuneFactory, CountryFactory
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.institutions.factories import InstitutionWithMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory
from tests.utils.test import BASE_NUM_QUERIES


class TestApplicantsAPI:
    URL = reverse_lazy("v1:applicants-list")

    def test_login_as_job_seeker(self, api_client):
        user = JobSeekerFactory()
        api_client.force_authenticate(user)

        response = api_client.get(self.URL, format="json")
        assert response.status_code == 403

    def test_login_as_prescriber_organisation(self, api_client):
        user = PrescriberOrganizationWithMembershipFactory().members.first()
        api_client.force_authenticate(user)

        response = api_client.get(self.URL, format="json")
        assert response.status_code == 403

    def test_login_as_institution(self, api_client):
        user = InstitutionWithMembershipFactory().members.first()
        api_client.force_authenticate(user)

        response = api_client.get(self.URL, format="json")
        assert response.status_code == 403

    def test_api_user_has_non_memberships(self, api_client):
        # Connected user must have a membership
        user = EmployerFactory()

        api_client.force_authenticate(user)
        response = api_client.get(self.URL, format="json")

        assert response.status_code == 403

    def test_api_user_is_not_only_admin(self, api_client):
        # Connected user must be admin of all their structures
        user = CompanyFactory(with_membership=True).members.first()
        CompanyMembershipFactory(is_admin=False, user=user)

        api_client.force_authenticate(user)
        response = api_client.get(self.URL, format="json")

        assert response.status_code == 403

    def test_login_as_siae(self, api_client):
        # Connect with an admin user with member of a single SIAE
        user = CompanyFactory(with_membership=True).members.first()
        api_client.force_authenticate(user)

        with assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # companymembership.is_admin check (ApplicantsAPIPermission)
            + 1  # get_queryset: job_application subquery (job_applications__to_company_id__in)
            + 1  # get queryset main query.
        ):
            response = api_client.get(self.URL, format="json")
        assert response.status_code == 200
        assert response.json().get("results") == []

    @pytest.mark.parametrize(
        ("mode_multi_structures", "uid_structures", "expected_first_names"),
        [
            ("", "", ["Bob", "Dylan"]),
            ("1", "", ["Bob", "Dylan", "Casper", "Nicholas"]),
            ("", "76c51a19-0ae9-420c-b2e3-0ab33836bd50", ["Bob", "Dylan"]),
            (
                "",
                "76c51a19-0ae9-420c-b2e3-0ab33836bd50,87c9e1d8-4498-40d7-a1df-1d3412378c87",
                ["Bob", "Dylan", "Casper", "Nicholas"],
            ),
            ("1", "76c51a19-0ae9-420c-b2e3-0ab33836bd50", ["Bob", "Dylan"]),
            ("", "I-am-not-a-uid", []),
            ("", "326dea3d-d17d-4f2c-9ffa-8e9cb305ae44", []),
        ],
    )
    def test_login_as_siae_multiple_memberships(
        self, api_client, mode_multi_structures, uid_structures, expected_first_names
    ):
        # Populate database with extra data to make sure filters work.
        JobApplicationFactory.create_batch(2, to_company_id=CompanyFactory().pk)

        # First company: 2 applicants, 3 job applications.
        company_1 = CompanyFactory(uid="76c51a19-0ae9-420c-b2e3-0ab33836bd50", with_membership=True)
        employer = company_1.members.first()
        JobApplicationFactory(job_seeker__first_name="Bob", to_company=company_1).job_seeker
        dylan = JobApplicationFactory(job_seeker__first_name="Dylan", to_company=company_1).job_seeker
        JobApplicationFactory(to_company_id=company_1.pk, job_seeker_id=dylan.pk)

        # Second company: 3 applicants, including one that is already in company_1.
        company_2 = CompanyFactory(
            uid="87c9e1d8-4498-40d7-a1df-1d3412378c87",
            with_membership=True,
            membership__is_admin=True,
            membership__user=employer,
        )
        JobApplicationFactory.create_batch(
            2, to_company_id=company_2.pk, job_seeker__first_name=factory.Iterator(["Casper", "Nicholas"])
        )
        JobApplicationFactory(to_company_id=company_2.pk, job_seeker_id=dylan.pk)

        num_queries = (
            BASE_NUM_QUERIES
            + 1  # companymembership.is_admin check (ApplicantsAPIPermission)
            + 1  # get_queryset: companies_uids aggregation
            + 1  # get_queryset: Count job_applications (Exists JobApplication)
        )
        if len(expected_first_names) > 0:
            # Subquery returned results, so the main query is executed.
            num_queries = num_queries + 1  # get_queryset: Fetch User + Profile

        api_client.force_authenticate(employer)

        with assertNumQueries(num_queries):
            response = api_client.get(
                self.URL,
                format="json",
                data={
                    "mode_multi_structures": mode_multi_structures,
                    "uid_structures": uid_structures,
                },
            )
            assert response.status_code == 200
            results = response.json().get("results")
            assert sorted(expected_first_names) == sorted([result["prenom"] for result in results])
            assert len(results) == len(expected_first_names)

    def test_applicant_data_mode_multiple_structures(self, api_client):
        # First company: 2 applicants, 3 job applications.
        company_1 = CompanyFactory(with_membership=True)
        employer = company_1.members.first()
        bob = JobApplicationFactory(job_seeker__first_name="Bob", to_company=company_1).job_seeker
        dylan = JobApplicationFactory(job_seeker__first_name="Dylan", to_company=company_1).job_seeker
        JobApplicationFactory(to_company_id=company_1.pk, job_seeker_id=dylan.pk)

        # Second company: 1 applicant, 1 job application.
        company_2 = CompanyFactory(
            with_membership=True,
            membership__is_admin=True,
            membership__user=employer,
        )
        JobApplicationFactory(to_company_id=company_2.pk, job_seeker_id=dylan.pk)

        # Third company, which the api users doesn't belong to but has a job application
        # for an applicant in the 2 others companies
        company_3 = CompanyFactory()
        JobApplicationFactory(to_company_id=company_3.pk, job_seeker_id=dylan.pk)

        # Add birth data
        bob.jobseeker_profile.birth_place = CommuneFactory()
        bob.jobseeker_profile.birth_country = CountryFactory()
        bob.jobseeker_profile.save()
        dylan.jobseeker_profile.birth_place = CommuneFactory()
        dylan.jobseeker_profile.birth_country = CountryFactory()
        dylan.jobseeker_profile.save()

        num_queries = (
            BASE_NUM_QUERIES
            + 1  # companymembership.is_admin check (ApplicantsAPIPermission)
            + 1  # get_queryset: companies_uids aggregation
            + 1  # get_queryset: Count job_applications (Exists JobApplication)
            + 1  # get_queryset: Fetch User + Profile
        )

        api_client.force_authenticate(employer)

        with assertNumQueries(num_queries):
            response = api_client.get(self.URL, format="json", data={"mode_multi_structures": "1"})

        assert response.status_code == 200
        results = response.json().get("results")
        assert [
            {
                "civilite": dylan.title,
                "nom": dylan.last_name,
                "prenom": dylan.first_name,
                "courriel": dylan.email,
                "telephone": dylan.phone,
                "adresse": dylan.address_line_1,
                "complement_adresse": dylan.address_line_2,
                "code_postal": dylan.post_code,
                "ville": dylan.city,
                "date_naissance": str(dylan.jobseeker_profile.birthdate),
                "lieu_naissance": dylan.jobseeker_profile.birth_place.name,
                "pays_naissance": dylan.jobseeker_profile.birth_country.name,
                "lien_cv": None,
                "uid_structures": sorted([str(company_1.uid), str(company_2.uid)]),
            },
            {
                "civilite": bob.title,
                "nom": bob.last_name,
                "prenom": bob.first_name,
                "courriel": bob.email,
                "telephone": bob.phone,
                "adresse": bob.address_line_1,
                "complement_adresse": bob.address_line_2,
                "code_postal": bob.post_code,
                "ville": bob.city,
                "date_naissance": str(bob.jobseeker_profile.birthdate),
                "lieu_naissance": bob.jobseeker_profile.birth_place.name,
                "pays_naissance": bob.jobseeker_profile.birth_country.name,
                "lien_cv": None,
                "uid_structures": [str(company_1.uid)],
            },
        ] == results

    def test_applicant_data(self, api_client):
        company = CompanyFactory(with_membership=True)
        job_seeker1 = JobApplicationFactory(to_company=company).job_seeker
        # Will not refactor ASP factories:
        # - too long,
        # - not the point
        # - scheduled in a future PR
        # => will use some hard-coded values until then
        job_seeker1.address_line_1 = "address test"
        job_seeker1.address_line_2 = "address 2"
        job_seeker1.post_code = "37000"
        job_seeker1.city = "TOURS"
        job_seeker1.save()
        job_seeker1.jobseeker_profile.birth_place = CommuneFactory()
        job_seeker1.jobseeker_profile.birth_country = CountryFactory()
        job_seeker1.jobseeker_profile.save()
        job_seeker2 = JobApplicationFactory(to_company=company).job_seeker
        job_seeker2.address_line_1 = "2nd address test"
        job_seeker2.address_line_2 = "2nd address 2"
        job_seeker2.post_code = "59000"
        job_seeker2.city = "LILLE"
        job_seeker2.save()
        job_seeker2.jobseeker_profile.birth_place = CommuneFactory()
        job_seeker2.jobseeker_profile.birth_country = CountryFactory()
        job_seeker2.jobseeker_profile.save()
        user = company.members.first()

        api_client.force_authenticate(user)
        with assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # companymembership.is_admin check (ApplicantsAPIPermission)
            + 1  # get_queryset: companies_uids aggregation
            + 1  # get_queryset: Count job_applications (Exists JobApplication)
            + 1  # get_queryset: Fetch User + Profile
        ):
            response = api_client.get(self.URL, format="json")

        assert response.status_code == 200

        # Ordered by decreasing pk, hence the swap
        [result_for_jobseeker2, result_for_jobseeker1] = response.json().get("results")

        for job_seeker, result in zip(
            [job_seeker1, job_seeker2],
            [result_for_jobseeker1, result_for_jobseeker2],
        ):
            assert {
                "civilite": job_seeker.title,
                "nom": job_seeker.last_name,
                "prenom": job_seeker.first_name,
                "courriel": job_seeker.email,
                "telephone": job_seeker.phone,
                "adresse": job_seeker.address_line_1,
                "complement_adresse": job_seeker.address_line_2,
                "code_postal": job_seeker.post_code,
                "ville": job_seeker.city,
                "date_naissance": str(job_seeker.jobseeker_profile.birthdate),
                "lieu_naissance": job_seeker.jobseeker_profile.birth_place.name,
                "pays_naissance": job_seeker.jobseeker_profile.birth_country.name,
                "lien_cv": None,
                "uid_structures": [str(company.uid)],
            } == result

    def test_rate_limiting(self, api_client):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        api_client.force_authenticate(user)
        # settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["user"]
        for _ in range(120):
            response = api_client.get(self.URL, format="json")
            assert response.status_code == 200
        response = api_client.get(self.URL, format="json")
        # Rate-limited.
        assert response.status_code == 429
