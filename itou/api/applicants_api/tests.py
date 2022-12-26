from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from itou.asp.factories import CommuneFactory, CountryFactory
from itou.institutions.factories import InstitutionWithMembershipFactory
from itou.job_applications.factories import JobApplicationFactory
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeFactory
from itou.users.factories import JobSeekerFactory


class ApplicantsAPITest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("v1:applicants-list")

    def test_login_as_job_seeker(self):
        user = JobSeekerFactory()
        self.client.force_authenticate(user)

        response = self.client.get(self.url, format="json")
        assert response.status_code == 403

    def test_login_as_prescriber_organisation(self):
        user = PrescriberOrganizationWithMembershipFactory().members.first()
        self.client.force_authenticate(user)

        response = self.client.get(self.url, format="json")
        assert response.status_code == 403

    def test_login_as_institution(self):
        user = InstitutionWithMembershipFactory().members.first()
        self.client.force_authenticate(user)

        response = self.client.get(self.url, format="json")
        assert response.status_code == 403

    def test_api_user_has_unique_siae_membership(self):
        # Connected user must only be member of target SIAE
        user = SiaeFactory(with_membership=True).members.first()
        SiaeFactory(with_membership=True).members.add(user)

        self.client.force_authenticate(user)
        response = self.client.get(self.url, format="json")

        assert response.status_code == 403

    def test_api_user_is_admin(self):
        # Connected user must only be admin of target SIAE
        user = SiaeFactory(with_membership=True).members.first()
        membership = user.siaemembership_set.first()
        membership.is_admin = False
        membership.save()

        self.client.force_authenticate(user)
        response = self.client.get(self.url, format="json")

        assert response.status_code == 403

    def test_login_as_siae(self):
        # Connect with an admin user with member of a sigle SIAE
        user = SiaeFactory(with_membership=True).members.first()
        self.client.force_authenticate(user)

        response = self.client.get(self.url, format="json")
        assert response.status_code == 200
        assert response.json().get("results") == []

    def test_applicant_data(self):
        siae = SiaeFactory(with_membership=True)
        job_seeker = JobApplicationFactory(to_siae=siae).job_seeker
        # Will not refactor ASP factories:
        # - too long,
        # - not the point
        # - scheduled in a future PR
        # => will use some hard-coded values until then
        job_seeker.address_line_1 = "address test"
        job_seeker.address_line_2 = "address 2"
        job_seeker.post_code = "37000"
        job_seeker.city = "TOURS"
        job_seeker.resume_link = "https://myresume.com/me"
        job_seeker.birth_place = CommuneFactory()
        job_seeker.birth_country = CountryFactory()
        job_seeker.save()
        user = siae.members.first()

        self.client.force_authenticate(user)
        response = self.client.get(self.url, format="json")

        assert response.status_code == 200

        [result] = response.json().get("results")

        assert {
            "civilite": job_seeker.title,
            "nom": job_seeker.first_name,
            "prenom": job_seeker.last_name,
            "courriel": job_seeker.email,
            "telephone": job_seeker.phone,
            "adresse": job_seeker.address_line_1,
            "complement_adresse": job_seeker.address_line_2,
            "code_postal": job_seeker.post_code,
            "ville": job_seeker.city,
            "date_naissance": str(job_seeker.birthdate),
            "lieu_naissance": job_seeker.birth_place.name,
            "pays_naissance": job_seeker.birth_country.name,
            "lien_cv": job_seeker.resume_link,
        } == result
