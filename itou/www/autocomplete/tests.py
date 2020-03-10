import json

from django.test import TestCase
from django.urls import reverse

from itou.cities.factories import create_test_cities
from itou.jobs.factories import create_test_romes_and_appellations


class JobsAutocompleteTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(["N1101", "N4105"])
        cls.url = reverse("autocomplete:jobs")

    def test_search_multi_words(self):
        response = self.client.get(self.url, {"term": "cariste ferroviaire"})
        self.assertEqual(response.status_code, 200)
        expected = [
            {
                "value": "Agent / Agente cariste de livraison ferroviaire (N1101)",
                "code": "10357",
                "rome": "N1101",
                "name": "Agent / Agente cariste de livraison ferroviaire",
            }
        ]
        self.assertEqual(json.loads(response.content), expected)

    def test_search_multi_words_with_exclusion(self):
        response = self.client.get(self.url, {"term": "cariste ferroviaire", "code": "10357"})
        self.assertEqual(response.status_code, 200)
        expected = b"[]"
        self.assertEqual(response.content, expected)

    def test_search_case_insensitive_and_explicit_rome_code(self):
        response = self.client.get(self.url, {"term": "CHAUFFEUR livreuse n4105"})
        self.assertEqual(response.status_code, 200)
        expected = [
            {
                "value": "Chauffeur-livreur / Chauffeuse-livreuse (N4105)",
                "code": "11999",
                "rome": "N4105",
                "name": "Chauffeur-livreur / Chauffeuse-livreuse",
            }
        ]
        self.assertEqual(json.loads(response.content), expected)

    def test_search_empty_chars(self):
        response = self.client.get(self.url, {"term": "    "})
        self.assertEqual(response.status_code, 200)
        expected = b"[]"
        self.assertEqual(response.content, expected)

    def test_search_full_label(self):
        response = self.client.get(
            self.url, {"term": "Conducteur / Conductrice de chariot élévateur de l'armée (N1101)"}
        )
        self.assertEqual(response.status_code, 200)
        expected = [
            {
                "value": "Conducteur / Conductrice de chariot élévateur de l'armée (N1101)",
                "code": "12918",
                "rome": "N1101",
                "name": "Conducteur / Conductrice de chariot élévateur de l'armée",
            }
        ]
        self.assertEqual(json.loads(response.content), expected)

    def test_search_special_chars(self):
        response = self.client.get(
            self.url, {"term": "conducteur:* & & de:* & !chariot:* & <eleva:*>>>> & armee:* & `(((()))`):*"}
        )
        self.assertEqual(response.status_code, 200)
        expected = [
            {
                "value": "Conducteur / Conductrice de chariot élévateur de l'armée (N1101)",
                "code": "12918",
                "rome": "N1101",
                "name": "Conducteur / Conductrice de chariot élévateur de l'armée",
            }
        ]
        self.assertEqual(json.loads(response.content), expected)


class CitiesAutocompleteTest(TestCase):
    def test_autocomplete(self):

        create_test_cities(["67"], num_per_department=10)

        url = reverse("autocomplete:cities")

        response = self.client.get(url, {"term": "alte"})
        self.assertEqual(response.status_code, 200)
        expected = [
            {"value": "Altenheim (67)", "slug": "altenheim-67"},
            {"value": "Altorf (67)", "slug": "altorf-67"},
            {"value": "Alteckendorf (67)", "slug": "alteckendorf-67"},
            {"value": "Albé (67)", "slug": "albe-67"},
            {"value": "Altwiller (67)", "slug": "altwiller-67"},
        ]
        self.assertEqual(json.loads(response.content), expected)

        response = self.client.get(url, {"term": "    "})
        self.assertEqual(response.status_code, 200)
        expected = b"[]"
        self.assertEqual(response.content, expected)

        response = self.client.get(url, {"term": "paris"})
        self.assertEqual(response.status_code, 200)
        expected = b"[]"
        self.assertEqual(response.content, expected)
