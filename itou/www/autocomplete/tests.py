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
        assert response.json() == expected

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
        assert response.json() == expected

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
        assert response.json() == expected

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
        assert response.json() == expected

    def test_search_filter_with_rome_code(self):
        appellation = Appellation.objects.autocomplete("conducteur", limit=1, rome_code="N1101")[0]
        assert appellation.code == "12918"
        assert appellation.name == "Conducteur / Conductrice de chariot élévateur de l'armée"

        appellation = Appellation.objects.autocomplete("conducteur", limit=1, rome_code="N4105")[0]
        assert appellation.code == "12859"
        assert appellation.name == "Conducteur collecteur / Conductrice collectrice de lait"


class CitiesAutocompleteTest(TestCase):
    def test_autocomplete(self):

        create_test_cities(["01", "75", "93"], num_per_department=20)

        url = reverse("autocomplete:cities")

        response = self.client.get(url, {"term": "sai"})
        assert response.status_code == 200
        assert response.json() == [
            {"slug": "saint-genis-pouilly-01", "value": "Saint-Genis-Pouilly (01)"},
            {"slug": "saint-jean-de-gonville-01", "value": "Saint-Jean-de-Gonville (01)"},
            {"slug": "saint-sulpice-01", "value": "Saint-Sulpice (01)"},
            {"slug": "le-pre-saint-gervais-93", "value": "Le Pré-Saint-Gervais (93)"},
        ]

        # the request still finds results when dashes were forgotten
        response = self.client.get(url, {"term": "saint g"})
        assert response.status_code == 200
        assert response.json() == [
            {"slug": "saint-genis-pouilly-01", "value": "Saint-Genis-Pouilly (01)"},
            {"slug": "le-pre-saint-gervais-93", "value": "Le Pré-Saint-Gervais (93)"},
        ]

        # and is also able to remove the dashes if entered
        response = self.client.get(url, {"term": "la cour"})
        assert response.status_code == 200
        assert response.json() == [{"slug": "la-courneuve-93", "value": "La Courneuve (93)"}]

        response = self.client.get(url, {"term": "chat"})
        assert response.status_code == 200
        assert response.json() == [
            {"slug": "bage-le-chatel-01", "value": "Bâgé-le-Châtel (01)"},
        ]

        response = self.client.get(url, {"term": "    "})
        assert response.status_code == 200
        expected = b"[]"
        assert response.content == expected

        response = self.client.get(url, {"term": "paris"})
        assert response.status_code == 200
        assert response.json() == [
            {"slug": "paris-75", "value": "Paris (75)"},
            {"slug": "paris-10e-arrondissement-75", "value": "Paris 10e Arrondissement (75)"},
            {"slug": "paris-11e-arrondissement-75", "value": "Paris 11e Arrondissement (75)"},
            {"slug": "paris-12e-arrondissement-75", "value": "Paris 12e Arrondissement (75)"},
            {"slug": "paris-13e-arrondissement-75", "value": "Paris 13e Arrondissement (75)"},
            {"slug": "paris-14e-arrondissement-75", "value": "Paris 14e Arrondissement (75)"},
            {"slug": "paris-15e-arrondissement-75", "value": "Paris 15e Arrondissement (75)"},
            {"slug": "paris-17e-arrondissement-75", "value": "Paris 17e Arrondissement (75)"},
            {"slug": "paris-18e-arrondissement-75", "value": "Paris 18e Arrondissement (75)"},
            {"slug": "paris-19e-arrondissement-75", "value": "Paris 19e Arrondissement (75)"},
            {"slug": "paris-1er-arrondissement-75", "value": "Paris 1er Arrondissement (75)"},
            {"slug": "paris-20e-arrondissement-75", "value": "Paris 20e Arrondissement (75)"},
            {"slug": "paris-2e-arrondissement-75", "value": "Paris 2e Arrondissement (75)"},
            {"slug": "paris-3e-arrondissement-75", "value": "Paris 3e Arrondissement (75)"},
            {"slug": "paris-4e-arrondissement-75", "value": "Paris 4e Arrondissement (75)"},
            {"slug": "paris-5e-arrondissement-75", "value": "Paris 5e Arrondissement (75)"},
            {"slug": "paris-6e-arrondissement-75", "value": "Paris 6e Arrondissement (75)"},
            {"slug": "paris-7e-arrondissement-75", "value": "Paris 7e Arrondissement (75)"},
            {"slug": "paris-8e-arrondissement-75", "value": "Paris 8e Arrondissement (75)"},
            {"slug": "paris-9e-arrondissement-75", "value": "Paris 9e Arrondissement (75)"},
        ]

        response = self.client.get(url, {"term": "paris 8"})
        assert response.status_code == 200
        assert response.json() == [
            {"slug": "paris-8e-arrondissement-75", "value": "Paris 8e Arrondissement (75)"},
        ]

        response = self.client.get(url, {"term": "toulouse"})
        assert response.status_code == 200
        assert response.json() == []

    def test_queryset_is_ordered_before_truncation(self):
        create_test_cities(["01", "02", "54", "57", "62", "75", "93"], num_per_department=20)
        response = self.client.get(reverse("autocomplete:cities"), {"term": "e"})
        assert response.status_code == 200
        assert response.json() == [
            {"slug": "eclimeux-62", "value": "Éclimeux (62)"},
            {"slug": "epiez-sur-chiers-54", "value": "Épiez-sur-Chiers (54)"},
            {"slug": "erbeviller-sur-amezule-54", "value": "Erbéviller-sur-Amezule (54)"},
            {"slug": "beny-01", "value": "Bény (01)"},
            {"slug": "celles-sur-aisne-02", "value": "Celles-sur-Aisne (02)"},
            {"slug": "helstroff-57", "value": "Helstroff (57)"},
            {"slug": "le-pre-saint-gervais-93", "value": "Le Pré-Saint-Gervais (93)"},
            {"slug": "remies-02", "value": "Remies (02)"},
            {"slug": "remilly-57", "value": "Rémilly (57)"},
            {"slug": "sevran-93", "value": "Sevran (93)"},
            {"slug": "verneuil-sur-serre-02", "value": "Verneuil-sur-Serre (02)"},
            {"slug": "chenicourt-54", "value": "Chenicourt (54)"},
            {"slug": "hoeville-54", "value": "Hoéville (54)"},
            {"slug": "tremblay-en-france-93", "value": "Tremblay-en-France (93)"},
            {"slug": "viels-maisons-02", "value": "Viels-Maisons (02)"},
            {"slug": "bage-le-chatel-01", "value": "Bâgé-le-Châtel (01)"},
            {"slug": "joyeux-01", "value": "Joyeux (01)"},
            {"slug": "moyen-54", "value": "Moyen (54)"},
            {"slug": "noyelles-les-vermelles-62", "value": "Noyelles-lès-Vermelles (62)"},
            {"slug": "wimereux-62", "value": "Wimereux (62)"},
            {"slug": "agnieres-62", "value": "Agnières (62)"},
            {"slug": "cattenom-57", "value": "Cattenom (57)"},
            {"slug": "schneckenbusch-57", "value": "Schneckenbusch (57)"},
            {"slug": "baslieux-54", "value": "Baslieux (54)"},
            {"slug": "boissey-01", "value": "Boissey (01)"},
            {"slug": "burthecourt-aux-chenes-54", "value": "Burthecourt-aux-Chênes (54)"},
            {"slug": "dhuizel-02", "value": "Dhuizel (02)"},
            {"slug": "dompierre-sur-chalaronne-01", "value": "Dompierre-sur-Chalaronne (01)"},
            {"slug": "longuenesse-62", "value": "Longuenesse (62)"},
            {"slug": "montreuil-93", "value": "Montreuil (93)"},
            {"slug": "sainte-austreberthe-62", "value": "Sainte-Austreberthe (62)"},
            {"slug": "foncquevillers-62", "value": "Foncquevillers (62)"},
            {"slug": "oigny-en-valois-02", "value": "Oigny-en-Valois (02)"},
            {"slug": "ottange-57", "value": "Ottange (57)"},
            {"slug": "noisy-le-grand-93", "value": "Noisy-le-Grand (93)"},
            {"slug": "paris-1er-arrondissement-75", "value": "Paris 1er Arrondissement (75)"},
            {"slug": "paris-2e-arrondissement-75", "value": "Paris 2e Arrondissement (75)"},
            {"slug": "paris-3e-arrondissement-75", "value": "Paris 3e Arrondissement (75)"},
            {"slug": "paris-4e-arrondissement-75", "value": "Paris 4e Arrondissement (75)"},
            {"slug": "paris-5e-arrondissement-75", "value": "Paris 5e Arrondissement (75)"},
            {"slug": "paris-6e-arrondissement-75", "value": "Paris 6e Arrondissement (75)"},
            {"slug": "paris-7e-arrondissement-75", "value": "Paris 7e Arrondissement (75)"},
            {"slug": "paris-8e-arrondissement-75", "value": "Paris 8e Arrondissement (75)"},
            {"slug": "paris-9e-arrondissement-75", "value": "Paris 9e Arrondissement (75)"},
            {"slug": "saint-genis-pouilly-01", "value": "Saint-Genis-Pouilly (01)"},
            {"slug": "saint-jean-de-gonville-01", "value": "Saint-Jean-de-Gonville (01)"},
            {"slug": "acquin-westbecourt-62", "value": "Acquin-Westbécourt (62)"},
            {"slug": "bainville-sur-madon-54", "value": "Bainville-sur-Madon (54)"},
            {"slug": "la-courneuve-93", "value": "La Courneuve (93)"},
            {"slug": "paris-10e-arrondissement-75", "value": "Paris 10e Arrondissement (75)"},
        ]


class CommunesAutocompleteTest(TestCase):
    def test_autocomplete(self):

        url = reverse("autocomplete:communes")

        response = self.client.get(url, {"term": "sai"})
        assert response.status_code == 200
        assert response.json() == [
            {"code": "64483", "department": "064", "value": "SAINT-JEAN-DE-LUZ (064)"},
            {"code": "62758", "department": "062", "value": "SAINT-MARTIN-BOULOGNE (062)"},
        ]

        response = self.client.get(url, {"term": "    "})
        assert response.status_code == 200
        assert response.json() == []

        response = self.client.get(url, {"term": "ILL"})
        assert response.status_code == 200
        assert response.json() == [
            {"code": "59350", "department": "059", "value": "LILLE (059)"},
            {"code": "37273", "department": "037", "value": "VILLE-AUX-DAMES (037)"},
            {"code": "07141", "department": "007", "value": "LENTILLERES (007)"},
            {"code": "13200", "department": "013", "value": "MARSEILLE (013)"},
            {"code": "83100", "department": "083", "value": "PUGET-VILLE (083)"},
        ]
