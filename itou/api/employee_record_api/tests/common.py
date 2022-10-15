from rest_framework.test import APITestCase


class EmployeeRecordApiTestCase(APITestCase):
    fixtures = [
        "test_asp_INSEE_communes_factory.json",
        "test_asp_INSEE_countries_factory.json",
    ]
