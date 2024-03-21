from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from tests.companies.factories import CompanyFactory


class EmployeeRecordThrottleTest(APITestCase):
    def test_throttling(self):
        client = APIClient()
        user = CompanyFactory(with_membership=True).members.first()
        client.force_authenticate(user)
        url = reverse("v1:employee-records-list")
        # EmployeeRecordRateThrottle.rate
        for _ in range(60):
            response = client.get(url, format="json")
            assert response.status_code == 200
        # Too fast, Jacky, one too many
        response = client.get(url, format="json")
        assert response.status_code == 429
