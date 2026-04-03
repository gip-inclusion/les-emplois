import factory
import pytest
from django.urls import reverse_lazy
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries

from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.institutions.factories import InstitutionFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory


class TestApplicantsAPI:
    URL = reverse_lazy("v1:applicants-list")

    def test_login_as_job_seeker(self, api_client):
        user = JobSeekerFactory()
        api_client.force_authenticate(user)

        response = api_client.get(self.URL, format="json")
        assert response.status_code == 403

    def test_login_as_prescriber_organisation(self, api_client):
        user = PrescriberOrganizationFactory(with_membership=True).members.first()
        api_client.force_authenticate(user)

        response = api_client.get(self.URL, format="json")
        assert response.status_code == 403

    def test_login_as_institution(self, api_client):
        user = InstitutionFactory(with_membership=True).members.first()
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

    def test_login_as_siae(self, api_client, snapshot):
        # Connect with an admin user with member of a single SIAE
        user = CompanyFactory(with_membership=True).members.first()
        api_client.force_authenticate(user)

        with assertSnapshotQueries(snapshot):
            response = api_client.get(self.URL, format="json")
        assert response.status_code == 200
        assert response.json().get("results") == []

    @pytest.mark.parametrize(
        ("mode_multi_structures", "uid_structures", "expected_first_names"),
        [
            pytest.param("", "", ["Bob", "Dylan"], id="single"),
            pytest.param("1", "", ["Bob", "Dylan", "Casper", "Nicholas"], id="multi"),
            pytest.param("", "76c51a19-0ae9-420c-b2e3-0ab33836bd50", ["Bob", "Dylan"], id="single_structure_id"),
            pytest.param(
                "",
                "76c51a19-0ae9-420c-b2e3-0ab33836bd50,87c9e1d8-4498-40d7-a1df-1d3412378c87",
                ["Bob", "Dylan", "Casper", "Nicholas"],
                id="single_multiple_structure_id",
            ),
            pytest.param("1", "76c51a19-0ae9-420c-b2e3-0ab33836bd50", ["Bob", "Dylan"], id="multi_structure_id"),
            pytest.param("", "I-am-not-a-uid", [], id="single_not_uid"),
            pytest.param("", "326dea3d-d17d-4f2c-9ffa-8e9cb305ae44", [], id="single_nonexistent_uid"),
        ],
    )
    def test_login_as_siae_multiple_membership(
        self, api_client, mode_multi_structures, uid_structures, expected_first_names, snapshot
    ):
        # Populate database with extra data to make sure filters work.
        JobApplicationFactory.create_batch(2, sent_by_prescriber_alone=True, to_company_id=CompanyFactory().pk)

        # First company: 2 applicants, 3 job applications.
        company_1 = CompanyFactory(uid="76c51a19-0ae9-420c-b2e3-0ab33836bd50", with_membership=True)
        employer = company_1.members.first()
        JobApplicationFactory(
            sent_by_prescriber_alone=True, job_seeker__first_name="Bob", to_company=company_1
        ).job_seeker
        dylan = JobApplicationFactory(
            sent_by_prescriber_alone=True, job_seeker__first_name="Dylan", to_company=company_1
        ).job_seeker
        JobApplicationFactory(sent_by_prescriber_alone=True, to_company_id=company_1.pk, job_seeker_id=dylan.pk)

        # Second company: 3 applicants, including one that is already in company_1.
        company_2 = CompanyFactory(
            uid="87c9e1d8-4498-40d7-a1df-1d3412378c87",
            with_membership=True,
            membership__is_admin=True,
            membership__user=employer,
        )
        JobApplicationFactory.create_batch(
            2,
            sent_by_prescriber_alone=True,
            to_company_id=company_2.pk,
            job_seeker__first_name=factory.Iterator(["Casper", "Nicholas"]),
        )
        JobApplicationFactory(sent_by_prescriber_alone=True, to_company_id=company_2.pk, job_seeker_id=dylan.pk)

        api_client.force_authenticate(employer)

        with assertSnapshotQueries(snapshot):
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

    def test_applicant_data_mode_multiple_structures(self, api_client, snapshot):
        # First company: 2 applicants, 3 job applications.
        company_1 = CompanyFactory(with_membership=True)
        employer = company_1.members.first()
        bob = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker__first_name="Bob",
            job_seeker__born_in_france=True,
            to_company=company_1,
        ).job_seeker
        dylan = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker__first_name="Dylan",
            job_seeker__born_in_france=True,
            to_company=company_1,
        ).job_seeker
        JobApplicationFactory(sent_by_prescriber_alone=True, to_company_id=company_1.pk, job_seeker_id=dylan.pk)

        # Second company: 1 applicant, 1 job application.
        company_2 = CompanyFactory(
            with_membership=True,
            membership__is_admin=True,
            membership__user=employer,
        )
        JobApplicationFactory(sent_by_prescriber_alone=True, to_company_id=company_2.pk, job_seeker_id=dylan.pk)

        # Third company, which the api users doesn't belong to but has a job application
        # for an applicant in the 2 others companies
        company_3 = CompanyFactory()
        JobApplicationFactory(sent_by_prescriber_alone=True, to_company_id=company_3.pk, job_seeker_id=dylan.pk)

        api_client.force_authenticate(employer)

        with assertSnapshotQueries(snapshot):
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

    def test_applicant_data(self, api_client, snapshot):
        company = CompanyFactory(with_membership=True)
        job_seeker1 = JobApplicationFactory(
            sent_by_prescriber_alone=True, to_company=company, job_seeker__born_in_france=True
        ).job_seeker
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
        job_seeker2 = JobApplicationFactory(
            sent_by_prescriber_alone=True, to_company=company, job_seeker__born_in_france=True
        ).job_seeker
        job_seeker2.address_line_1 = "2nd address test"
        job_seeker2.address_line_2 = "2nd address 2"
        job_seeker2.post_code = "59000"
        job_seeker2.city = "LILLE"
        job_seeker2.save()
        user = company.members.first()

        api_client.force_authenticate(user)
        with assertSnapshotQueries(snapshot):
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

    @freeze_time()
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
