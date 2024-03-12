from django.urls import reverse_lazy
from rest_framework.test import APIClient, APITestCase

from tests.asp.factories import CommuneFactory, CountryFactory
from tests.companies.factories import CompanyFactory
from tests.institutions.factories import InstitutionWithMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import BASE_NUM_QUERIES


class ApplicantsAPITest(APITestCase):
    URL = reverse_lazy("v1:applicants-list")

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_login_as_job_seeker(self):
        user = JobSeekerFactory()
        self.client.force_authenticate(user)

        response = self.client.get(self.URL, format="json")
        assert response.status_code == 403

    def test_login_as_prescriber_organisation(self):
        user = PrescriberOrganizationWithMembershipFactory().members.first()
        self.client.force_authenticate(user)

        response = self.client.get(self.URL, format="json")
        assert response.status_code == 403

    def test_login_as_institution(self):
        user = InstitutionWithMembershipFactory().members.first()
        self.client.force_authenticate(user)

        response = self.client.get(self.URL, format="json")
        assert response.status_code == 403

    def test_api_user_has_unique_siae_membership(self):
        # Connected user must only be member of target SIAE
        user = CompanyFactory(with_membership=True).members.first()
        CompanyFactory(with_membership=True).members.add(user)

        self.client.force_authenticate(user)
        response = self.client.get(self.URL, format="json")

        assert response.status_code == 403

    def test_api_user_is_admin(self):
        # Connected user must only be admin of target SIAE
        user = CompanyFactory(with_membership=True).members.first()
        membership = user.companymembership_set.first()
        membership.is_admin = False
        membership.save()

        self.client.force_authenticate(user)
        response = self.client.get(self.URL, format="json")

        assert response.status_code == 403

    def test_login_as_siae(self):
        # Connect with an admin user with member of a sigle SIAE
        user = CompanyFactory(with_membership=True).members.first()
        self.client.force_authenticate(user)

        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # companymembership check (ApplicantsAPIPermission)
            + 1  # siaes_companymembership fetch for request.user (get_queryset)
            + 1  # count users
        ):
            response = self.client.get(self.URL, format="json")
        assert response.status_code == 200
        assert response.json().get("results") == []

    def test_applicant_data(self):
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

        self.client.force_authenticate(user)
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # companymembership check (ApplicantsAPIPermission)
            + 1  # siaes_companymembership fetch for request.user (get_queryset)
            + 1  # count users
            + 1  # fetch users
            + 1  # prefetch linked job applications
        ):
            response = self.client.get(self.URL, format="json")

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
                "date_naissance": str(job_seeker.birthdate),
                "lieu_naissance": job_seeker.jobseeker_profile.birth_place.name,
                "pays_naissance": job_seeker.jobseeker_profile.birth_country.name,
                "lien_cv": None,
            } == result

    def test_rate_limiting(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        self.client.force_authenticate(user)
        # settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["user"]
        for _ in range(120):
            response = self.client.get(self.URL, format="json")
            assert response.status_code == 200
        response = self.client.get(self.URL, format="json")
        # Rate-limited.
        assert response.status_code == 429
