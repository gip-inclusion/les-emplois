import json

from django.test import TestCase
from django.urls import reverse

from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation, Rome


class FixturesTest(TestCase):

    def test_create_test_romes_and_appellations(self):
        create_test_romes_and_appellations(['M1805', 'N1101'], appellations_per_rome=2)
        self.assertEqual(Rome.objects.count(), 2)
        self.assertEqual(Appellation.objects.count(), 4)
        self.assertEqual(Appellation.objects.filter(rome_id='M1805').count(), 2)
        self.assertEqual(Appellation.objects.filter(rome_id='N1101').count(), 2)


class AutocompleteViewTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(['N1101', 'N4105'])
        cls.url = reverse('jobs:autocomplete')

    def test_multi_words(self):
        response = self.client.get(self.url, {'term': 'cariste ferroviaire'})
        self.assertEqual(response.status_code, 200)
        expected = [
            {
                'value': 'Agent / Agente cariste de livraison ferroviaire (N1101)',
                'code': '10357',
                'rome': 'N1101',
                'short_name': 'Agent / Agente cariste de livraison ferroviaire',
            }
        ]
        self.assertEqual(json.loads(response.content), expected)

    def test_multi_words_with_exclusion(self):
        response = self.client.get(self.url, {'term': 'cariste ferroviaire', 'code': '10357'})
        self.assertEqual(response.status_code, 200)
        expected = b'[]'
        self.assertEqual(response.content, expected)

    def test_case_insensitive_and_explicit_rome_code(self):
        response = self.client.get(self.url, {'term': 'CHAUFFEUR livreuse N4105'})
        self.assertEqual(response.status_code, 200)
        expected = [
            {
                'value': 'Chauffeur-livreur / Chauffeuse-livreuse (N4105)',
                'code': '11999',
                'rome': 'N4105',
                'short_name': 'Chauffeur-livreur / Chauffeuse-livreuse',
            }
        ]
        self.assertEqual(json.loads(response.content), expected)

    def test_empty_chars(self):
        response = self.client.get(self.url, {'term': '    '})
        self.assertEqual(response.status_code, 200)
        expected = b'[]'
        self.assertEqual(response.content, expected)
