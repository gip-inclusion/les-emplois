import json

from django.test import TestCase
from django.urls import reverse

from itou.cities.factories import create_test_cities
from itou.cities.models import City


class FixturesTest(TestCase):

    def test_create_test_cities(self):
        create_test_cities(['62', '67', '93'], num_per_department=10)
        self.assertEqual(City.objects.all().count(), 30)
        self.assertEqual(City.objects.filter(department='62').count(), 10)
        self.assertEqual(City.objects.filter(department='67').count(), 10)
        self.assertEqual(City.objects.filter(department='93').count(), 10)


class ViewsTest(TestCase):

    def test_autocomplete(self):

        create_test_cities(['67'], num_per_department=10)

        url = reverse('city:autocomplete')

        response = self.client.get(url, {'term': 'alte'})
        self.assertEqual(response.status_code, 200)
        expected = [{
          'label': 'Alteckendorf (67)',
          'value': 'Alteckendorf (67)',
          'slug': 'alteckendorf-67'
        }, {
          'label': 'Altenheim (67)',
          'value': 'Altenheim (67)',
          'slug': 'altenheim-67'
        }]
        self.assertEqual(json.loads(response.content), expected)

        response = self.client.get(url, {'term': '    '})
        self.assertEqual(response.status_code, 200)
        expected = b'[]'
        self.assertEqual(response.content, expected)

        response = self.client.get(url, {'term': 'paris'})
        self.assertEqual(response.status_code, 200)
        expected = b'[]'
        self.assertEqual(response.content, expected)
