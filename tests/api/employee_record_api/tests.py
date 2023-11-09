from unittest import mock

import pytest
from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.utils.mocks.address_format import mock_get_geocoding_data
from tests.employee_record.factories import EmployeeRecordWithProfileFactory
from tests.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory
from tests.users.factories import DEFAULT_PASSWORD, EmployerFactory
from tests.utils.test import BASE_NUM_QUERIES


ENDPOINT_URL = reverse("v1:employee-records-list")


class EmployeeRecordAPIPermissionsTest(APITestCase):
    token_url = reverse("v1:token-auth")

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # We only care about status filtering: no coherence check on ASP return values
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        self.employee_record_ready = EmployeeRecordWithProfileFactory(
            job_application=job_application, status=Status.READY
        )

        self.user = self.employee_record_ready.job_application.to_siae.members.first()
        self.unauthorized_user = EmployerFactory()

    def test_permissions_ok_with_token(self):
        """
        Standard use-case: using external API client with token auth
        """
        data = {"username": self.user.email, "password": DEFAULT_PASSWORD}
        response = self.client.post(self.token_url, data, format="json")
        assert response.status_code == 200

        token = response.json().get("token")
        assert token is not None

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        response = self.client.get(ENDPOINT_URL, format="json")

        # Result list found but empty
        assert response.status_code == 200

    def test_permissions_ko_with_token(self):
        data = {"username": self.unauthorized_user.email, "password": DEFAULT_PASSWORD}
        response = self.client.post(self.token_url, data, format="json")
        assert response.status_code == 200

        token = response.json().get("token")
        assert token is not None

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        response = self.client.get(ENDPOINT_URL, format="json")

        # Result list exists, but user is not member of any SIAE
        assert response.status_code == 403

    def test_permission_ok_with_session(self):
        """
        A session authentication is valid to use the API (same security level as token)
        => Allows testing in DEV context
        """
        self.client.force_login(self.user)

        response = self.client.get(ENDPOINT_URL, format="json")
        assert response.status_code == 200

    def test_permission_ko_with_session(self):
        self.client.force_login(self.unauthorized_user)

        response = self.client.get(ENDPOINT_URL, format="json")
        self.assertRedirects(response, reverse("account_logout"), status_code=302, target_status_code=200)


@pytest.mark.usefixtures("unittest_compatibility")
class EmployeeRecordAPIFetchListTest(APITestCase):
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def setUp(self, _mock):
        super().setUp()
        # We only care about status filtering: no coherence check on ASP return values
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        self.employee_record = EmployeeRecord.from_job_application(job_application)
        self.employee_record.update_as_ready()

        self.siae = job_application.to_siae
        self.employer = self.siae.members.first()
        self.user = job_application.job_seeker

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_fetch_employee_record_list(self, _mock):
        """
        Fetch list of employee records with and without `status` query param
        """
        # Using session auth (same as token but less steps)
        self.client.force_login(self.employer)

        # Get list without filtering by status (PROCESSED)
        # note: there is no way to create a processed employee record
        # (and this is perfectly normal)
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)
        process_code, process_message = "0000", "La ligne de la fiche salarié a été enregistrée avec succès."

        # There should be no result at this point
        response = self.client.get(ENDPOINT_URL, format="json")

        assert response.status_code == 200

        result = response.json()

        assert len(result.get("results")) == 0

        self.employee_record.update_as_processed(process_code, process_message, "{}")
        response = self.client.get(ENDPOINT_URL, format="json")

        assert response.status_code == 200

        result = response.json()

        assert len(result.get("results")) == 1
        self.assertContains(response, self.siae.siret)

        # status = SENT
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory(to_siae=self.siae)
        employee_record_sent = EmployeeRecord.from_job_application(job_application=job_application)
        employee_record_sent.update_as_ready()

        # There should be no result at this point
        response = self.client.get(ENDPOINT_URL + "?status=SENT", format="json")

        assert response.status_code == 200

        result = response.json()

        assert len(result.get("results")) == 0

        employee_record_sent.update_as_sent(self.faker.asp_batch_filename(), 1, None)
        response = self.client.get(ENDPOINT_URL + "?status=SENT", format="json")

        assert response.status_code == 200

        result = response.json()

        assert len(result.get("results")) == 1
        self.assertContains(response, self.siae.siret)

        # status = REJECTED
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory(to_siae=self.siae)
        employee_record_rejected = EmployeeRecord.from_job_application(job_application=job_application)
        employee_record_rejected.update_as_ready()
        employee_record_rejected.update_as_sent(self.faker.asp_batch_filename(), 1, None)

        # There should be no result at this point
        response = self.client.get(ENDPOINT_URL + "?status=REJECTED", format="json")
        assert response.status_code == 200

        result = response.json()

        assert len(result.get("results")) == 0

        err_code, err_message = "12", "JSON Invalide"
        employee_record_rejected.update_as_rejected(err_code, err_message, None)

        # Status case is not important
        response = self.client.get(ENDPOINT_URL + "?status=rEjEcTeD", format="json")
        assert response.status_code == 200

        result = response.json()

        assert len(result.get("results")) == 1
        self.assertContains(response, self.siae.siret)

    def test_fetch_employee_record_list_query_count(self):
        self.client.force_login(self.employer)

        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # Get the session
            + 3  # Get the user, its memberships, and the SIAEs (middleware)
            + 1  # Permissions check (EmployeeRecordAPIPermission)
            + 1  # Get SIAEs of the member (EmployeeRecordViewSet.get_queryset)
            + 2  # Get the employee records and the total count
            + 3  # Save the session (with transaction)
        ):
            self.client.get(ENDPOINT_URL, data={"status": list(Status)}, format="json")

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_show_phone_email_api(self, _mock):
        # BUGFIX:
        # Test that employee phone number and email address are passed
        # to API serializer.
        self.client.force_login(self.employer)

        response = self.client.get(ENDPOINT_URL + "?status=READY", format="json")

        assert response.status_code == 200

        json = response.json()

        assert len(json.get("results")) == 1

        results = json["results"][0]

        assert results.get("adresse").get("adrTelephone") == self.user.phone
        assert results.get("adresse").get("adrMail") == self.user.email


@pytest.mark.usefixtures("unittest_compatibility")
class EmployeeRecordAPIParametersTest(APITestCase):
    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_status_parameter(self, _mock):
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)
        employee_record.update_as_ready()

        member = employee_record.job_application.to_siae.members.first()
        self.client.force_login(member)

        response = self.client.get(ENDPOINT_URL + "?status=READY", format="json")

        assert response.status_code == 200

        results = response.json()

        assert len(results.get("results")) == 1
        # there is no "direct" way to match an API result to given employee record
        # (f.i. no pk exported)
        result = results.get("results")[0]

        assert result.get("personnePhysique", {}).get("passIae") == job_application.approval.number

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_status_array_parameter(self, _mock):
        job_application_1 = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application_1)
        employee_record.update_as_ready()

        job_application_2 = JobApplicationWithCompleteJobSeekerProfileFactory(
            to_siae=employee_record.job_application.to_siae
        )
        employee_record = EmployeeRecord.from_job_application(job_application_2)
        employee_record.update_as_ready()
        employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)

        member = employee_record.job_application.to_siae.members.first()
        self.client.force_login(member)
        response = self.client.get(ENDPOINT_URL + "?status=READY", format="json")

        assert response.status_code == 200

        results = response.json()

        assert len(results.get("results")) == 1

        response = self.client.get(ENDPOINT_URL + "?status=SENT&status=READY", format="json")

        assert response.status_code == 200

        results = response.json()

        assert len(results.get("results")) == 2

        # results are ordered by created_at DESC
        result_1 = results.get("results")[0]
        result_2 = results.get("results")[1]

        assert result_1.get("personnePhysique", {}).get("passIae") == job_application_2.approval.number
        assert result_2.get("personnePhysique", {}).get("passIae") == job_application_1.approval.number

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_created_parameter(self, _mock):
        job_application = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecord.from_job_application(job_application)
        employee_record.status = Status.PROCESSED  # Default status if no `status` params present
        employee_record.save()

        today = timezone.localdate()
        today_param = f"{today:%Y-%m-%d}"
        yesterday_param = f"{today - relativedelta(days=1):%Y-%m-%d}"

        member = employee_record.job_application.to_siae.members.first()
        self.client.force_login(member)
        response = self.client.get(ENDPOINT_URL + f"?created={today_param}", format="json")

        assert response.status_code == 200

        results = response.json()

        assert len(results.get("results")) == 1
        result = results.get("results")[0]

        assert result.get("siret") == job_application.to_siae.siret

        response = self.client.get(ENDPOINT_URL + f"?created={yesterday_param}", format="json")
        results = response.json()

        assert response.status_code == 200
        assert not results.get("results")

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_since_parameter(self, _mock):
        today = f"{timezone.localdate():%Y-%m-%d}"
        sooner_ts = timezone.localtime() - relativedelta(days=3)
        sooner = f"{sooner_ts:%Y-%m-%d}"
        ancient_ts = timezone.localtime() - relativedelta(months=2)
        ancient = f"{ancient_ts:%Y-%m-%d}"

        job_application_1 = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record_1 = EmployeeRecord.from_job_application(job_application_1)
        employee_record_1.created_at = sooner_ts
        employee_record_1.status = Status.PROCESSED  # Default status if no `status` params present
        employee_record_1.save()

        job_application_2 = JobApplicationWithCompleteJobSeekerProfileFactory(to_siae=job_application_1.to_siae)
        employee_record_2 = EmployeeRecord.from_job_application(job_application_2)
        employee_record_2.created_at = ancient_ts
        employee_record_2.status = Status.PROCESSED  # Default status if no `status` params present
        employee_record_2.save()

        member = employee_record_1.job_application.to_siae.members.first()

        self.client.force_login(member)
        response = self.client.get(ENDPOINT_URL + f"?since={today}", format="json")

        assert response.status_code == 200

        results = response.json()

        assert not results.get("results")

        response = self.client.get(ENDPOINT_URL + f"?since={sooner}", format="json")

        assert response.status_code == 200

        results = response.json().get("results")

        assert results
        assert results[0].get("siret") == job_application_1.to_siae.siret

        response = self.client.get(ENDPOINT_URL + f"?since={ancient}", format="json")

        assert response.status_code == 200

        results = response.json().get("results")

        assert len(results) == 2

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_chain_parameters(self, _mock):
        sooner_ts = timezone.now() - relativedelta(days=3)
        sooner = f"{sooner_ts:%Y-%m-%d}"
        ancient_ts = timezone.now() - relativedelta(months=2)
        ancient = f"{ancient_ts:%Y-%m-%d}"

        job_application_1 = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record_1 = EmployeeRecord.from_job_application(job_application_1)
        employee_record_1.created_at = sooner_ts
        employee_record_1.save()  # in state NEW

        job_application_2 = JobApplicationWithCompleteJobSeekerProfileFactory(to_siae=job_application_1.to_siae)
        employee_record_2 = EmployeeRecord.from_job_application(job_application_2)
        employee_record_2.created_at = ancient_ts
        employee_record_2.update_as_ready()

        member = employee_record_1.job_application.to_siae.members.first()

        self.client.force_login(member)
        response = self.client.get(ENDPOINT_URL + "?status=NEW", format="json")

        assert response.status_code == 200

        results = response.json().get("results")

        assert len(results) == 1

        response = self.client.get(ENDPOINT_URL + f"?status=NEW&created={sooner}", format="json")

        assert response.status_code == 200

        results = response.json().get("results")

        assert len(results) == 1

        response = self.client.get(ENDPOINT_URL + f"?status=READY&since={ancient}", format="json")

        assert response.status_code == 200

        results = response.json().get("results")

        assert len(results) == 1

        response = self.client.get(ENDPOINT_URL + f"?status=READY&since={sooner}", format="json")

        assert response.status_code == 200

        results = response.json().get("results")

        assert len(results) == 0
