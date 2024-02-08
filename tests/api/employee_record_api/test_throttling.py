from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from itou.api.employee_record_api.viewsets import EmployeeRecordRateThrottle
from tests.companies.factories import CompanyFactory
from tests.users.factories import DEFAULT_PASSWORD


ENDPOINT_URL = reverse("v1:employee-records-list")


class EmployeeRecordThrottleTest(APITestCase):
    # This a simple smoke test, goal is *not* testing DRF throttling

    def test_basic_ko_throttling(self):
        client = APIClient()
        user = CompanyFactory(with_membership=True).members.first()

        client.login(username=user.username, password=DEFAULT_PASSWORD)

        response = client.get(ENDPOINT_URL, format="json")
        assert response.status_code == 200

        # Too fast, Jacky, one too many
        for _ in range(EmployeeRecordRateThrottle.EMPLOYEE_RECORD_API_REQUESTS_NUMBER):
            response = client.get(ENDPOINT_URL, format="json")

        assert response.status_code == 429

    def test_basic_ok_throttling(self):
        client = APIClient()
        user = CompanyFactory(with_membership=True).members.first()

        client.login(username=user.username, password=DEFAULT_PASSWORD)

        response = client.get(ENDPOINT_URL, format="json")
        assert response.status_code == 200

        # Should hold it : a total of EMPLOYEE_RECORD_API_REQUESTS_NUMBER is sent
        for _ in range(EmployeeRecordRateThrottle.EMPLOYEE_RECORD_API_REQUESTS_NUMBER - 1):
            response = client.get(ENDPOINT_URL, format="json")

        assert response.status_code == 200
