import copy
import json
import logging

import httpx
import respx
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from itou.utils.apis import api_entreprise
from itou.utils.mocks.api_entreprise import ETABLISSEMENT_API_RESULT_MOCK, INSEE_API_RESULT_MOCK


@override_settings(
    API_INSEE_BASE_URL="https://fake.insee.url", API_INSEE_CONSUMER_KEY="foo", API_INSEE_CONSUMER_SECRET="bar"
)
class INSEEApiTest(SimpleTestCase):
    @respx.mock
    def test_access_token(self):
        endpoint = respx.post(f"{settings.API_INSEE_BASE_URL}/token").respond(200, json=INSEE_API_RESULT_MOCK)

        access_token = api_entreprise.get_access_token()

        assert endpoint.called
        assert b"grant_type=client_credentials" in endpoint.calls.last.request.content
        assert endpoint.calls.last.request.headers["Authorization"].startswith("Basic ")
        assert access_token == INSEE_API_RESULT_MOCK["access_token"]

    @respx.mock
    def test_access_token_with_http_error(self):
        respx.post(f"{settings.API_INSEE_BASE_URL}/token").respond(400)

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            access_token = api_entreprise.get_access_token()

        assert access_token is None
        assert "Failed to retrieve an access token" in cm.records[0].message
        assert cm.records[0].exc_info[0] is httpx.HTTPStatusError

    @respx.mock
    def test_access_token_with_json_error(self):
        respx.post(f"{settings.API_INSEE_BASE_URL}/token").respond(200, content=b"not-json")

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            access_token = api_entreprise.get_access_token()

        assert access_token is None
        assert "Failed to retrieve an access token" in cm.records[0].message
        assert cm.records[0].exc_info[0] is json.JSONDecodeError


@override_settings(
    API_INSEE_BASE_URL="https://fake.insee.url",
    API_INSEE_SIRENE_BASE_URL="https://api.entreprise.fake.com",
    API_INSEE_CONSUMER_KEY="foo",
    API_INSEE_CONSUMER_SECRET="bar",
)
class ApiEntrepriseTest(SimpleTestCase):
    def setUp(self):
        super().setUp()

        self.token_endpoint = respx.post(f"{settings.API_INSEE_BASE_URL}/token").respond(
            200,
            json=INSEE_API_RESULT_MOCK,
        )

        self.siret_endpoint = respx.get(f"{settings.API_INSEE_SIRENE_BASE_URL}/siret/26570134200148")

    @respx.mock
    def test_etablissement_get_or_error(self):
        self.siret_endpoint.respond(200, json=ETABLISSEMENT_API_RESULT_MOCK)

        etablissement, error = api_entreprise.etablissement_get_or_error("26570134200148")

        assert error is None
        assert etablissement.name == "CENTRE COMMUNAL D'ACTION SOCIALE"
        assert etablissement.address_line_1 == "22 RUE DU WAD BILLY"
        assert etablissement.address_line_2 == "22-24"
        assert etablissement.post_code == "57000"
        assert etablissement.city == "METZ"
        assert etablissement.department == "57"
        assert not etablissement.is_closed
        assert etablissement.is_head_office

    @respx.mock
    def test_etablissement_get_or_error_with_closed_status(self):
        data = copy.deepcopy(ETABLISSEMENT_API_RESULT_MOCK)
        data["etablissement"]["periodesEtablissement"][0]["etatAdministratifEtablissement"] = "F"
        self.siret_endpoint.respond(200, json=data)

        etablissement, error = api_entreprise.etablissement_get_or_error("26570134200148")

        assert error is None
        assert etablissement.is_closed

    @respx.mock
    def test_etablissement_get_or_error_without_token(self):
        self.token_endpoint.respond(404)

        result = api_entreprise.etablissement_get_or_error("whatever")

        assert result == (None, "Problème de connexion à la base Sirene. Essayez ultérieurement.")

    @respx.mock
    def test_etablissement_get_or_error_with_request_error(self):
        self.siret_endpoint.mock(side_effect=httpx.RequestError)

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            result = api_entreprise.etablissement_get_or_error("26570134200148")

        assert result == (None, "Problème de connexion à la base Sirene. Essayez ultérieurement.")
        assert cm.records[0].message.startswith("A request to the INSEE API failed")

    @respx.mock
    def test_etablissement_get_or_error_with_other_http_bad_request_error(self):
        self.siret_endpoint.respond(400)

        result = api_entreprise.etablissement_get_or_error("26570134200148")

        assert result == (None, "Erreur dans le format du SIRET : « 26570134200148 ».")

    @respx.mock
    def test_etablissement_get_or_error_with_other_http_forbidden_error(self):
        self.siret_endpoint.respond(403)

        result = api_entreprise.etablissement_get_or_error("26570134200148")

        assert result == (None, "Cette entreprise a exercé son droit d'opposition auprès de l'INSEE.")

    @respx.mock
    def test_etablissement_get_or_error_with_other_http_not_found_error(self):
        self.siret_endpoint.respond(404)

        result = api_entreprise.etablissement_get_or_error("26570134200148")

        assert result == (None, "SIRET « 26570134200148 » non reconnu.")

    @respx.mock
    def test_etablissement_get_or_error_with_http_error(self):
        self.siret_endpoint.respond(401)

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            result = api_entreprise.etablissement_get_or_error("26570134200148")

        assert result == (None, "Problème de connexion à la base Sirene. Essayez ultérieurement.")
        assert cm.records[0].message.startswith("Error while fetching")

    @respx.mock
    def test_etablissement_get_or_error_when_content_is_not_json(self):
        self.siret_endpoint.respond(200, content=b"not-json")

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            result = api_entreprise.etablissement_get_or_error("26570134200148")

        assert result == (None, "Le format de la réponse API Entreprise est non valide.")
        assert cm.records[0].message.startswith("Invalid format of response from API Entreprise")
        assert cm.records[0].exc_info[0] is json.JSONDecodeError

    @respx.mock
    def test_etablissement_get_or_error_when_content_is_missing_data(self):
        self.siret_endpoint.respond(200, json={})

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            result = api_entreprise.etablissement_get_or_error("26570134200148")

        assert result == (None, "Le format de la réponse API Entreprise est non valide.")
        assert cm.records[0].message.startswith("Invalid format of response from API Entreprise")
        assert cm.records[0].exc_info[0] is KeyError

    @respx.mock
    def test_etablissement_get_or_error_when_content_is_missing_historical_data(self):
        data = copy.deepcopy(ETABLISSEMENT_API_RESULT_MOCK)
        data["etablissement"]["periodesEtablissement"] = []
        self.siret_endpoint.respond(200, json=data)

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            result = api_entreprise.etablissement_get_or_error("26570134200148")

        assert result == (None, "Le format de la réponse API Entreprise est non valide.")
        assert cm.records[0].message.startswith("Invalid format of response from API Entreprise")
        assert cm.records[0].exc_info[0] is IndexError

    @respx.mock
    def test_etablissement_get_or_error_with_missing_address_number(self):
        data = copy.deepcopy(ETABLISSEMENT_API_RESULT_MOCK)
        data["etablissement"]["adresseEtablissement"]["numeroVoieEtablissement"] = None
        self.siret_endpoint.respond(200, json=data)

        etablissement, error = api_entreprise.etablissement_get_or_error("26570134200148")

        assert error is None
        assert etablissement.address_line_1 == "RUE DU WAD BILLY"

    @respx.mock
    def test_etablissement_get_or_error_with_empty_address(self):
        data = copy.deepcopy(ETABLISSEMENT_API_RESULT_MOCK)
        data["etablissement"]["adresseEtablissement"] = {
            "complementAdresseEtablissement": None,
            "numeroVoieEtablissement": None,
            "typeVoieEtablissement": None,
            "libelleVoieEtablissement": None,
            "codePostalEtablissement": None,
            "libelleCommuneEtablissement": None,
            "codeCommuneEtablissement": None,
        }
        self.siret_endpoint.respond(200, json=data)

        etablissement, error = api_entreprise.etablissement_get_or_error("26570134200148")

        assert error is None
        assert etablissement.address_line_1 is None
        assert etablissement.address_line_2 is None
        assert etablissement.post_code is None
        assert etablissement.city is None
        assert etablissement.department is None
