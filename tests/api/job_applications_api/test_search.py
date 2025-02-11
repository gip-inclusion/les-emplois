from datetime import date

import pytest
from django.urls import reverse_lazy

from itou.api.auth import ServiceAccount
from itou.api.models import DepartmentToken
from tests.api.utils import _str_with_tz
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.test import assertSnapshotQueries


VALID_SEARCH_DATA = {
    "nir": "269054958815780",
    "nom": "DURAND",
    "prenom": "NATHALIE",
    "date_naissance": "1969-05-12",
}


class TestJobApplicationSearchApi:
    ENDPOINT_URL = reverse_lazy("v1:job-applications-search")

    @pytest.fixture(autouse=True)
    def setup_method(self, settings):
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] |= {"job-applications-search": "10/minute"}

        self.job_seeker_1 = JobSeekerFactory(
            jobseeker_profile__nir="269054958815780",
            jobseeker_profile__birthdate=date(1969, 5, 12),
            last_name="Durand",
            first_name="Nathalie",
            born_in_france=True,
            with_address=True,
        )
        self.job_seeker_2 = JobSeekerFactory(
            jobseeker_profile__nir="199127524528683",
            jobseeker_profile__birthdate=date(1999, 12, 3),
            last_name="Dupont-Maréchal",
            first_name="Léopold",
            born_outside_france=True,
            with_address=True,
        )

        self.job_application = JobApplicationFactory(
            job_seeker=self.job_seeker_1,
            sent_by_authorized_prescriber_organisation=True,
            with_approval=True,
            was_hired=True,
        )
        JobApplicationFactory(job_seeker=self.job_seeker_1)
        JobApplicationFactory(job_seeker=self.job_seeker_1)
        JobApplicationFactory(job_seeker=self.job_seeker_2)
        JobApplicationFactory(job_seeker=self.job_seeker_2)

        self.token = DepartmentToken.objects.create(department="01", label="Token tests département 01")

    @pytest.mark.parametrize(
        "method_name,expected",
        [
            ("get", 405),
            ("post", 200),
            ("put", 405),
            ("patch", 405),
            ("delete", 405),
            ("head", 405),
            ("options", 200),
        ],
    )
    def test_http_method(self, api_client, method_name, expected):
        http_method = getattr(api_client, method_name)
        api_client.force_authenticate(ServiceAccount(), self.token)
        response = http_method(self.ENDPOINT_URL, VALID_SEARCH_DATA, format="json")
        assert response.status_code == expected

    @pytest.mark.parametrize(
        "user_factory",
        [
            lambda: JobSeekerFactory(),
            lambda: PrescriberFactory(),
            lambda: EmployerFactory(),
            lambda: LaborInspectorFactory(),
            lambda: ItouStaffFactory(is_superuser=True),
        ],
    )
    def test_unauthorized_access(self, api_client, user_factory):
        api_client.force_authenticate(user_factory())
        response = api_client.post(self.ENDPOINT_URL, VALID_SEARCH_DATA, format="json")
        assert response.status_code == 403

    def test_performances(self, api_client, snapshot):
        api_client.force_authenticate(ServiceAccount(), self.token)
        with assertSnapshotQueries(snapshot):
            api_client.post(self.ENDPOINT_URL, VALID_SEARCH_DATA, format="json")

    def test_exact_match(self, api_client):
        api_client.force_authenticate(ServiceAccount(), self.token)
        response = api_client.post(self.ENDPOINT_URL, VALID_SEARCH_DATA, format="json")
        assert response.status_code == 200
        assert len(response.json()["results"]) == 3

    def test_fuzzy_match_on_control_payload(self, api_client):
        api_client.force_authenticate(ServiceAccount(), self.token)
        payload = {
            "nir": "269054958815780",
            "nom": "DURANT",
            "prenom": "NATALIE",
            "date_naissance": "1969-05-12",
        }
        response = api_client.post(self.ENDPOINT_URL, payload, format="json")
        assert response.status_code == 200
        assert len(response.json()["results"]) == 3

        # date_naissance must be exact
        payload["date_naissance"] = "1969-05-21"
        response = api_client.post(self.ENDPOINT_URL, payload, format="json")
        assert response.status_code == 200
        assert len(response.json()["results"]) == 0

    def test_fuzzy_and_unaccent_match(self, api_client):
        api_client.force_authenticate(ServiceAccount(), self.token)
        payload = {
            "nir": "199127524528683",
            "nom": "Dupont-Maréchal",
            "prenom": "Léopold",
            "date_naissance": "1999-12-03",
        }
        response = api_client.post(self.ENDPOINT_URL, payload, format="json")
        assert response.status_code == 200
        assert len(response.json()["results"]) == 2

        payload["nom"] = "Dupont Maréchal"
        payload["prenom"] = "leopold"
        response = api_client.post(self.ENDPOINT_URL, payload, format="json")
        assert response.status_code == 200
        assert len(response.json()["results"]) == 2

        payload["nom"] = "Dupont"
        response = api_client.post(self.ENDPOINT_URL, payload, format="json")
        assert response.status_code == 200
        assert len(response.json()["results"]) == 2

        payload["nom"] = "Duport"
        response = api_client.post(self.ENDPOINT_URL, payload, format="json")
        assert response.status_code == 200
        assert len(response.json()["results"]) == 0

    def test_throttling(self, api_client):
        api_client.force_authenticate(ServiceAccount(), self.token)

        for _ in range(10):
            response = api_client.post(self.ENDPOINT_URL, VALID_SEARCH_DATA, format="json")
            assert response.status_code == 200

        response = api_client.post(self.ENDPOINT_URL, VALID_SEARCH_DATA, format="json")
        assert response.status_code == 429

    def test_serialized_data(self, api_client):
        api_client.force_authenticate(ServiceAccount(), self.token)

        response = api_client.post(self.ENDPOINT_URL, VALID_SEARCH_DATA, format="json")
        assert response.status_code == 200

        results = response.json()["results"]
        assert len(results) == 3

        first_application = results[-1]  # Reversed sorting
        assert first_application["cree_le"] == _str_with_tz(self.job_application.created_at)
        assert first_application["statut"] == self.job_application.state
        assert first_application["candidat_nom"] == self.job_seeker_1.last_name
        assert first_application["candidat_prenom"] == self.job_seeker_1.first_name
        assert first_application["candidat_nir"] == self.job_seeker_1.jobseeker_profile.nir
        assert first_application["candidat_email"] == self.job_seeker_1.email
        assert first_application["candidat_telephone"] == self.job_seeker_1.phone
        assert first_application["candidat_pass_iae_statut"] == self.job_application.approval.state
        assert first_application["candidat_pass_iae_numero"] == self.job_application.approval.number
        assert first_application["candidat_pass_iae_date_debut"] == self.job_application.approval.start_at.isoformat()
        assert first_application["candidat_pass_iae_date_fin"] == self.job_application.approval.end_at.isoformat()
        assert first_application["entreprise_type"] == self.job_application.to_company.kind
        assert first_application["entreprise_nom"] == self.job_application.to_company.display_name
        assert first_application["entreprise_siret"] == self.job_application.to_company.siret
        assert first_application["entreprise_adresse"] == self.job_application.to_company.address_on_one_line
        assert first_application["entreprise_email"] == self.job_application.to_company.email
        assert first_application["orientation_emetteur_type"] == self.job_application.sender_kind
        assert (
            first_application["orientation_emetteur_sous_type"]
            == self.job_application.sender_prescriber_organization.kind
        )
        assert first_application["orientation_emetteur_nom"] == self.job_application.sender.last_name
        assert first_application["orientation_emetteur_prenom"] == self.job_application.sender.first_name
        assert (
            first_application["orientation_emetteur_organisme"]
            == self.job_application.sender_prescriber_organization.name
        )
        assert (
            first_application["orientation_emetteur_organisme_email"]
            == self.job_application.sender_prescriber_organization.email
        )
        assert (
            first_application["orientation_emetteur_organisme_telephone"]
            == self.job_application.sender_prescriber_organization.phone
        )
        # FIXME(leo): add orientation_postes_recherches. Use snapshot?
        assert first_application["orientation_candidat_message"] == self.job_application.message
        assert first_application["orientation_candidat_cv"] == self.job_application.resume_link
        assert first_application["contrat_date_debut"] == self.job_application.hiring_start_at.isoformat()
        assert first_application["contrat_date_fin"] == self.job_application.hiring_end_at.isoformat()
        hired_job = self.job_application.hired_job
        assert first_application["contrat_poste_retenu"] == {
            "rome": hired_job.appellation.rome.code,
            "titre": hired_job.appellation.rome.name,
            "ville": hired_job.location.name if hired_job.location else hired_job.company.city,
        }
