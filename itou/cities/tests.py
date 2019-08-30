from django.test import TestCase

from itou.cities.factories import create_test_cities
from itou.cities.models import City


class FixturesTest(TestCase):
    def test_create_test_cities(self):
        create_test_cities(["62", "67", "93"], num_per_department=10)
        self.assertEqual(City.objects.count(), 30)
        self.assertEqual(City.objects.filter(department="62").count(), 10)
        self.assertEqual(City.objects.filter(department="67").count(), 10)
        self.assertEqual(City.objects.filter(department="93").count(), 10)
