import json
from datetime import date

import pytest
from django.urls import reverse_lazy
from freezegun import freeze_time

from itou.api.auth import ServiceAccount
from itou.api.job_application_api.serializers import JobApplicationSearchResponseSerializer
from itou.api.models import DepartmentToken
from itou.companies.models import Company
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplicationTransitionLog
from tests.api.utils import _str_with_tz
from tests.companies.factories import CompanyMembershipFactory
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
            nir="269054958815780",
            birthdate=date(1969, 5, 12),
            last_name="Durand",
            first_name="Nathalie",
            born_in_france=True,
            with_address=True,
        )
        self.job_seeker_2 = JobSeekerFactory(
            nir="199127524528683",
            birthdate=date(1999, 12, 3),
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

    def test_serialized_data(self, api_client, snapshot):
        api_client.force_authenticate(ServiceAccount(), self.token)
        with freeze_time("2025-02-14"):
            job_application = JobApplicationFactory(
                sent_by_authorized_prescriber_organisation=True,
                with_approval=True,
                was_hired=True,
                for_snapshot=True,
                sender_prescriber_organization__for_snapshot=True,
                sender_prescriber_organization__membership__user__for_snapshot=True,
                hired_job__for_snapshot=True,
                resume_link="https://server.com/rockie-balboa.pdf",
            )
            job_application.selected_jobs.set({job_application.hired_job})

        response = api_client.post(
            self.ENDPOINT_URL,
            {
                "nir": "290010101010125",
                "nom": "Doe",
                "prenom": "Jane",
                "date_naissance": "1990-01-01",
            },
            format="json",
        )
        assert response.status_code == 200
        assert json.dumps(response.json(), indent=4) == snapshot

    @pytest.mark.parametrize(
        "company_source,expected_len",
        [
            (Company.SOURCE_ASP, 14),
            (Company.SOURCE_GEIQ, 14),
            (Company.SOURCE_EA_EATT, 14),
            (Company.SOURCE_USER_CREATED, 9),
            (Company.SOURCE_STAFF_CREATED, 14),
        ],
    )
    def test_siret_siren(self, company_source, expected_len):
        self.job_application.to_company.source = company_source
        self.job_application.last_modification_at = self.job_application.updated_at  # Faked annotated attribute
        self.job_application.employer_email = self.job_application.to_company.email  # Faked annotated attribute
        assert (
            len(JobApplicationSearchResponseSerializer(self.job_application).data["entreprise_siret"]) == expected_len
        )

    def test_logs_annotations(self, api_client):
        api_client.force_authenticate(ServiceAccount(), self.token)

        # No transition logs
        # Must fallback on job application last update and company email
        response = api_client.post(self.ENDPOINT_URL, VALID_SEARCH_DATA, format="json")
        first_application = response.json()["results"][-1]  # Reversed sorting
        assert not self.job_application.logs.exists()
        assert first_application["dernier_changement_le"] == _str_with_tz(self.job_application.updated_at)
        assert first_application["entreprise_employeur_email"] == self.job_application.to_company.email

        # 'PROCESS' transition performed by employer
        # Both annotations should consider this transition log
        employer = self.job_application.to_company.members.first()
        employer_log = JobApplicationTransitionLog.objects.create(
            user=employer,
            job_application=self.job_application,
            to_state=JobApplicationState.PROCESSING,
        )
        response = api_client.post(self.ENDPOINT_URL, VALID_SEARCH_DATA, format="json")
        first_application = response.json()["results"][-1]  # Reversed sorting
        assert first_application["dernier_changement_le"] == _str_with_tz(employer_log.timestamp)
        assert first_application["entreprise_employeur_email"] == employer.email

        # 'ACCEPT' transition performed by staff user
        # last_modification_at should consider this transition log but employer_email the employer's one
        staff_user_log = JobApplicationTransitionLog.objects.create(
            user=ItouStaffFactory(),
            job_application=self.job_application,
            to_state=JobApplicationState.ACCEPTED,
        )
        response = api_client.post(self.ENDPOINT_URL, VALID_SEARCH_DATA, format="json")
        first_application = response.json()["results"][-1]  # Reversed sorting
        assert first_application["dernier_changement_le"] == _str_with_tz(staff_user_log.timestamp)
        assert first_application["entreprise_employeur_email"] == employer.email

        # 'CANCEL' transition performed by employer
        # Both annotations should consider this transition log again
        other_employer = CompanyMembershipFactory(company=self.job_application.to_company).user
        other_employer_log = JobApplicationTransitionLog.objects.create(
            user=other_employer,
            job_application=self.job_application,
            to_state=JobApplicationState.CANCELLED,
        )
        response = api_client.post(self.ENDPOINT_URL, VALID_SEARCH_DATA, format="json")
        first_application = response.json()["results"][-1]  # Reversed sorting
        assert first_application["dernier_changement_le"] == _str_with_tz(other_employer_log.timestamp)
        assert first_application["entreprise_employeur_email"] == other_employer.email
