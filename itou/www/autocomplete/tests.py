import json

from django.urls import reverse

from itou.cities.factories import create_test_cities
from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.siaes.factories import SiaeFactory
from itou.utils.test import TestCase


class JobsAutocompleteTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(["N1101", "N4105"])
        # Update:
        # - autocomplete URL now needs a SIAE parameter (for existing ROME filtering)
        # - this URL does not accept create / update / delete of elements (removed some some tests)
        cls.siae = SiaeFactory()
        cls.url = reverse("autocomplete:jobs")

    def test_search_multi_words(self):
        response = self.client.get(
            self.url,
            {
                "term": "cariste ferroviaire",
                "siae_id": self.siae.id,
            },
        )
        assert response.status_code == 200
        expected = [
            {
                "value": "Agent / Agente cariste de livraison ferroviaire (N1101)",
                "code": "10357",
                "rome": "N1101",
                "name": "Agent / Agente cariste de livraison ferroviaire",
            }
        ]
        assert json.loads(response.content) == expected

    def test_search_case_insensitive_and_explicit_rome_code(self):
        response = self.client.get(
            self.url,
            {
                "term": "CHAUFFEUR livreuse n4105",
                "siae_id": self.siae.id,
            },
        )
        assert response.status_code == 200
        expected = [
            {
                "value": "Chauffeur-livreur / Chauffeuse-livreuse (N4105)",
                "code": "11999",
                "rome": "N4105",
                "name": "Chauffeur-livreur / Chauffeuse-livreuse",
            }
        ]
        assert json.loads(response.content) == expected

    def test_search_empty_chars(self):
        response = self.client.get(
            self.url,
            {
                "term": "    ",
                "siae_id": self.siae.id,
            },
        )
        assert response.status_code == 200
        expected = b"[]"
        assert response.content == expected

    def test_search_full_label(self):
        response = self.client.get(
            self.url,
            {
                "term": "Conducteur / Conductrice de chariot élévateur de l'armée (N1101)",
                "siae_id": self.siae.id,
            },
        )
        assert response.status_code == 200
        expected = [
            {
                "value": "Conducteur / Conductrice de chariot élévateur de l'armée (N1101)",
                "code": "12918",
                "rome": "N1101",
                "name": "Conducteur / Conductrice de chariot élévateur de l'armée",
            }
        ]
        assert json.loads(response.content) == expected

    def test_search_special_chars(self):
        response = self.client.get(
            self.url,
            {
                "term": "conducteur:* & & de:* & !chariot:* & <eleva:*>>>> & armee:* & `(((()))`):*",
                "siae_id": self.siae.id,
            },
        )
        assert response.status_code == 200
        expected = [
            {
                "value": "Conducteur / Conductrice de chariot élévateur de l'armée (N1101)",
                "code": "12918",
                "rome": "N1101",
                "name": "Conducteur / Conductrice de chariot élévateur de l'armée",
            }
        ]
        assert json.loads(response.content) == expected

    def test_search_filter_with_rome_code(self):
        appellation = Appellation.objects.autocomplete("conducteur", limit=1, rome_code="N1101")[0]
        assert appellation.code == "12918"
        assert appellation.name == "Conducteur / Conductrice de chariot élévateur de l'armée"

        appellation = Appellation.objects.autocomplete("conducteur", limit=1, rome_code="N4105")[0]
        assert appellation.code == "12859"
        assert appellation.name == "Conducteur collecteur / Conductrice collectrice de lait"


class CitiesAutocompleteTest(TestCase):
    def test_autocomplete(self):

        create_test_cities(["01", "75"], num_per_department=20)

        url = reverse("autocomplete:cities")

        response = self.client.get(url, {"term": "sai"})
        assert response.status_code == 200
        assert json.loads(response.content) == [
            {"slug": "saint-sulpice-01", "value": "Saint-Sulpice (01)"},
            {"slug": "saint-genis-pouilly-01", "value": "Saint-Genis-Pouilly (01)"},
            {"slug": "saint-jean-de-gonville-01", "value": "Saint-Jean-de-Gonville (01)"},
        ]

        response = self.client.get(url, {"term": "    "})
        assert response.status_code == 200
        expected = b"[]"
        assert response.content == expected

        response = self.client.get(url, {"term": "paris"})
        assert response.status_code == 200
        assert json.loads(response.content) == [
            {"slug": "paris-75", "value": "Paris (75)"},
            {"slug": "paris-2e-arrondissement-75", "value": "Paris 2e Arrondissement (75)"},
            {"slug": "paris-3e-arrondissement-75", "value": "Paris 3e Arrondissement (75)"},
            {"slug": "paris-4e-arrondissement-75", "value": "Paris 4e Arrondissement (75)"},
            {"slug": "paris-5e-arrondissement-75", "value": "Paris 5e Arrondissement (75)"},
            {"slug": "paris-6e-arrondissement-75", "value": "Paris 6e Arrondissement (75)"},
            {"slug": "paris-7e-arrondissement-75", "value": "Paris 7e Arrondissement (75)"},
            {"slug": "paris-8e-arrondissement-75", "value": "Paris 8e Arrondissement (75)"},
            {"slug": "paris-9e-arrondissement-75", "value": "Paris 9e Arrondissement (75)"},
            {"slug": "paris-10e-arrondissement-75", "value": "Paris 10e Arrondissement (75)"},
        ]

        response = self.client.get(url, {"term": "paris 8"})
        assert response.status_code == 200
        assert json.loads(response.content) == [
            {"slug": "paris-8e-arrondissement-75", "value": "Paris 8e Arrondissement (75)"},
            # the trigram similarity allows for those results to show up, I'm not happy with it but
            # I won't look much more into it now. In my opinion they should be discarded since
            # they do not include an "8".
            {"slug": "paris-75", "value": "Paris (75)"},
            {"slug": "paris-2e-arrondissement-75", "value": "Paris 2e Arrondissement (75)"},
            {"slug": "paris-3e-arrondissement-75", "value": "Paris 3e Arrondissement (75)"},
            {"slug": "paris-4e-arrondissement-75", "value": "Paris 4e Arrondissement (75)"},
            {"slug": "paris-5e-arrondissement-75", "value": "Paris 5e Arrondissement (75)"},
            {"slug": "paris-6e-arrondissement-75", "value": "Paris 6e Arrondissement (75)"},
            {"slug": "paris-7e-arrondissement-75", "value": "Paris 7e Arrondissement (75)"},
            {"slug": "paris-9e-arrondissement-75", "value": "Paris 9e Arrondissement (75)"},
            {"slug": "paris-10e-arrondissement-75", "value": "Paris 10e Arrondissement (75)"},
        ]

        response = self.client.get(url, {"term": "toulouse"})
        assert response.status_code == 200
        assert json.loads(response.content) == []
