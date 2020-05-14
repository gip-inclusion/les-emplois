import json

from django.test import TestCase
from django.urls import reverse

from itou.cities.factories import create_test_cities
from itou.jobs.factories import create_test_romes_and_appellations
from itou.prescribers.factories import PrescriberOrganizationFactory
from itou.prescribers.models import PrescriberOrganization


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


class PrescriberAuthorizedOrganizationsAutocompleteTest(TestCase):
    def test_autocomplete(self):

        org_pe_validated = PrescriberOrganizationFactory(
            is_authorized=True,
            authorization_status=PrescriberOrganization.AuthorizationStatus.VALIDATED,
            kind=PrescriberOrganization.Kind.PE,
            name="Pôle emploi",
        )

        org_cap_emploi_validated = PrescriberOrganizationFactory(
            is_authorized=True,
            authorization_status=PrescriberOrganization.AuthorizationStatus.VALIDATED,
            kind=PrescriberOrganization.Kind.CAP_EMPLOI,
            name="Cap emploi",
        )

        org_spip_not_set = PrescriberOrganizationFactory(
            is_authorized=True,
            authorization_status=PrescriberOrganization.AuthorizationStatus.NOT_SET,
            kind=PrescriberOrganization.Kind.CAP_EMPLOI,
            name="SPIP",
        )

        org_orientator = PrescriberOrganizationFactory(
            is_authorized=True,
            authorization_status=PrescriberOrganization.AuthorizationStatus.NOT_REQUIRED,
            kind=PrescriberOrganization.Kind.OTHER,
            name="Orienteur",
        )

        url = reverse("autocomplete:prescriber_authorized_organizations")

        response = self.client.get(url, {"term": "Pôle"})
        self.assertEqual(response.status_code, 200)
        expected = []
        self.assertEqual(json.loads(response.content), expected)

        response = self.client.get(url, {"term": "Cap"})
        self.assertEqual(response.status_code, 200)
        expected = [{"value": org_cap_emploi_validated.name, "id": org_cap_emploi_validated.pk}]
        self.assertEqual(json.loads(response.content), expected)

        response = self.client.get(url, {"term": "spip"})
        self.assertEqual(response.status_code, 200)
        expected = [{"value": org_spip_not_set.name, "id": org_spip_not_set.pk}]
        self.assertEqual(json.loads(response.content), expected)

        response = self.client.get(url, {"term": "Orienteur"})
        self.assertEqual(response.status_code, 200)
        expected = []
        self.assertEqual(json.loads(response.content), expected)
