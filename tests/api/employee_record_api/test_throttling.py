from django.urls import reverse

from tests.companies.factories import CompanyFactory


class TestEmployeeRecordThrottle:
    def test_throttling(self, api_client):
        user = CompanyFactory(with_membership=True).members.first()
        api_client.force_authenticate(user)
        url = reverse("v1:employee-records-list")
        # EmployeeRecordRateThrottle.rate
        for _ in range(60):
            response = api_client.get(url, format="json")
            assert response.status_code == 200
        # Too fast, Jacky, one too many
        response = api_client.get(url, format="json")
        assert response.status_code == 429
