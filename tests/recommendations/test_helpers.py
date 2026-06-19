import dataclasses
import datetime

import pytest

from itou.recommendations.helpers import fetch_and_parse_user_data, get_user_data
from itou.utils.apis.pole_emploi import Endpoints
from itou.utils.mocks.pole_emploi import RESPONSES, ResponseKind


class TestGetUserData:
    @pytest.fixture(autouse=True)
    def setup_method(self, mocker):
        self.mock = mocker.patch("itou.recommendations.helpers.fetch_and_parse_user_data")

    def test_success(self):
        self.mock.return_value = "fetched_data"

        res = get_user_data("first_id")
        assert self.mock.call_count == 1
        assert res == "fetched_data"

        res = get_user_data("first_id")
        assert self.mock.call_count == 1
        assert res == "fetched_data"

        res = get_user_data("second_id")
        assert self.mock.call_count == 2
        assert res == "fetched_data"

    def test_failure(self):
        self.mock.side_effect = ValueError("any error")

        res = get_user_data("first_id")
        assert self.mock.call_count == 1
        assert res is None

        res = get_user_data("first_id")
        assert self.mock.call_count == 2  # nothing was cached, call it again
        assert res is None


class TestFetchAndParseUserData:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, respx_mock):
        settings.API_ESD = {
            "BASE_URL": "https://pe.fake",
            "AUTH_BASE_URL_AGENT": "https://auth.fr",
            "RECOMMENDATIONS_KEY": "foobar",
            "RECOMMENDATIONS_SECRET": "pe-secret",
        }
        respx_mock.post(
            f"{settings.API_ESD['AUTH_BASE_URL_AGENT']}/connexion/oauth2/access_token?realm=%2Fagent"
        ).respond(
            200,
            json={
                "token_type": "Bearer",
                "access_token": "Catwoman",
                "scope": "client_id h2a rechercheusager profil_accedant api_donnees-rqthv1 api_rechercher-usagerv2",
                "expires_in": 1499,
            },
        )
        respx_mock.post(f"{settings.API_ESD['BASE_URL']}{Endpoints.RECHERCHER_USAGER_NUMERO_FRANCE_TRAVAIL}").respond(
            200, json=RESPONSES[Endpoints.RECHERCHER_USAGER_NUMERO_FRANCE_TRAVAIL][ResponseKind.CERTIFIED]
        )
        respx_mock.get(settings.API_ESD["BASE_URL"] + Endpoints.INFORMATIONS_ADMINISTRATIVES_USAGER).respond(
            200, json=RESPONSES[Endpoints.INFORMATIONS_ADMINISTRATIVES_USAGER][ResponseKind.CERTIFIED]
        )
        respx_mock.get(settings.API_ESD["BASE_URL"] + Endpoints.STATUT_USAGER).respond(
            200, json=RESPONSES[Endpoints.STATUT_USAGER][ResponseKind.CERTIFIED]
        )
        respx_mock.get(settings.API_ESD["BASE_URL"] + Endpoints.LECTURE_ORIENTATION_USAGER).respond(
            200, json=RESPONSES[Endpoints.LECTURE_ORIENTATION_USAGER][ResponseKind.CERTIFIED]
        )
        respx_mock.get(settings.API_ESD["BASE_URL"] + Endpoints.DIAGNOSTIC_USAGER_DIAGNOSTIC_AGREGE).respond(
            200, json=RESPONSES[Endpoints.DIAGNOSTIC_USAGER_DIAGNOSTIC_AGREGE][ResponseKind.CERTIFIED]
        )

    def test_fetch_and_parse_user_data(self):
        user_data = fetch_and_parse_user_data("any_id")
        assert dataclasses.asdict(user_data) == {
            "administrative_data": {
                "address": {
                    "address_line_1": "93 Rue Marietton",
                    "address_line_2": "Résidence Les Tilleuls",
                    "city": "LYON",
                    "insee_code": "69389",
                    "post_code": "69009",
                },
                "birthdate": datetime.date(1998, 7, 11),
                "email": "john.doe@francetravail.fr",
                "first_name": "JOHN",
                "is_in_qpv": False,
                "last_name": "DOE",
                "phone": "0972723949",
                "title": "M.",
            },
            "consolidated_file": {
                "capacity_to_act": {
                    "author": {
                        "first_name": "Fernande",
                        "last_name": "Dupont",
                        "organization": "CDG Alpes Haute Provence",
                        "timestamp": datetime.datetime(2021, 5, 17, 14, 47, 11, tzinfo=datetime.UTC),
                    },
                    "label": "Possible perte de confiance",
                },
                "constraints": [
                    {
                        "author": {
                            "first_name": "Fernande",
                            "last_name": "Dupont",
                            "organization": "CDG Alpes Haute Provence",
                            "timestamp": datetime.datetime(2021, 5, 17, 14, 47, 11, tzinfo=datetime.UTC),
                        },
                        "details": [
                            "Faire un point complet sur sa mobilité",
                            "Accéder à un véhicule",
                            "Entretenir ou réparer son véhicule",
                            "Obtenir le permis de conduire (code / conduite)",
                            "Trouver une solution de transport (hors acquisition ou entretien de véhicule)",
                            "Travailler la mobilité psychologique",
                            "Aucun moyen de transport à disposition",
                            "Dépendant des transports en communs",
                            "Permis non valide / suspension de permis",
                        ],
                        "high_priority": True,
                        "impact": "FAIBLE",
                        "label": "Développer sa mobilité",
                    },
                ],
                "diagnoses": [
                    {
                        "author": {
                            "first_name": "Fernande",
                            "last_name": "Dupont",
                            "organization": "CDG Alpes Haute Provence",
                            "timestamp": datetime.datetime(2022, 12, 8, 23, 0, tzinfo=datetime.UTC),
                        },
                        "high_priority": False,
                        "name": "Boulanger",
                        "needs": [
                            {
                                "author": {
                                    "first_name": "Fernande",
                                    "last_name": "Dupont",
                                    "organization": "CDG Alpes Haute Provence",
                                    "timestamp": datetime.datetime(2019, 5, 17, 14, 47, 11, tzinfo=datetime.UTC),
                                },
                                "label": "Découvrir un métier ou un secteur d’activité",
                                "value": "BESOIN",
                            },
                            {
                                "author": {
                                    "first_name": "Fernande",
                                    "last_name": "Dupont",
                                    "organization": "CDG Alpes Haute Provence",
                                    "timestamp": datetime.datetime(2019, 5, 17, 14, 47, 11, tzinfo=datetime.UTC),
                                },
                                "label": "Confirmer son choix de métier",
                                "value": "POINT_FORT",
                            },
                        ],
                    },
                ],
                "digital_autonomy_constraint": {
                    "author": {
                        "first_name": "Fernande",
                        "last_name": "Dupont",
                        "organization": "CDG Alpes Haute Provence",
                        "timestamp": datetime.datetime(2021, 5, 17, 14, 47, 11, tzinfo=datetime.UTC),
                    },
                    "details": [
                        "Acquérir un équipement",
                        "Accéder à  une connexion internet",
                        "Maîtriser les fondamentaux du numérique",
                        "Absence d'équipement",
                        "Dispose d'un ordinateur",
                        "Dispose d'un smartphone",
                        "Dispose d'une tablette",
                        "Absence de maîtrise de l'équipement",
                        "Absence de connexion (zone blanche)",
                        "Absence de connexion (refus)",
                        "Absence de connexion (autre)",
                        "Absence d'adresse ou d'utilisation de la messagerie",
                        "Absence de mobilité pour accéder à un espace numérique",
                        "Difficulté à réaliser des démarches administratives en ligne",
                        "En difficulté sur le numérique (résultat Pix emploi <50%)",
                    ],
                    "high_priority": True,
                    "impact": "FAIBLE",
                    "label": "Accéder au numérique et en maîtriser les fondamentaux",
                },
                "digital_autonomy_need": {
                    "author": {
                        "first_name": "Fernande",
                        "last_name": "Dupont",
                        "organization": "CDG Alpes Haute Provence",
                        "timestamp": datetime.datetime(2021, 5, 17, 14, 47, 11, tzinfo=datetime.UTC),
                    },
                    "label": "Connaître et utiliser les services numériques",
                    "value": "BESOIN",
                },
            },
            "criteria": {
                "boe": True,
                "brsa": True,
                "currently_employed": True,
                "level_of_education": "AFS",
            },
            "status": {
                "deld": False,
                "detld": False,
                "registered": True,
                "since": datetime.date(2025, 6, 28),
            },
        }

    @pytest.mark.parametrize(
        "endpoint",
        [
            Endpoints.INFORMATIONS_ADMINISTRATIVES_USAGER,
            Endpoints.STATUT_USAGER,
            Endpoints.DIAGNOSTIC_USAGER_DIAGNOSTIC_AGREGE,
        ],
    )
    def test_204(self, respx_mock, settings, endpoint):
        respx_mock.get(settings.API_ESD["BASE_URL"] + endpoint).respond(
            204, json=RESPONSES[endpoint][ResponseKind.NO_DATA_FOUND]
        )
        with pytest.raises(ValueError):
            fetch_and_parse_user_data("any_id")
