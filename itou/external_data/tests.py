import json
import random

import requests_mock
from django.test import TestCase

import itou.external_data.apis.pe_connect as pec
from itou.users.factories import JobSeekerFactory

from .apis.pe_connect import import_user_data
from .models import ExternalDataImport


# Test data import status (All ok, failed, partial)

# Mock PE connect endpoints

FOO_TOKEN = "kreatur_token"

# CALL https://api.emploi-store.fr/partenaire/peconnect-individu/v1/userinfo:
_RESP_USER_INFO = {
    "giv/en_name": "Tom",
    "family_name": "Riddle",
    "gender": "male",
    "idIdentiteExterne": "46533ae7-da92-4614-9d9b-12c47a5d14c9",
    "email": "me@voldemort.com",
    "sub": "46533ae7-da92-4614-9d9b-12c47a5d14c9",
    "updated_at": 0,
}

# CALL https://api.emploi-store.fr/partenaire/peconnect-datenaissance/v1/etat-civil:
_RESP_USER_BIRTHDATE = {
    "codeCivilite": None,
    "libelleCivilite": None,
    "nomPatronymique": None,
    "nomMarital": None,
    "prenom": None,
    "dateDeNaissance": "1970-01-01T00:00:00+01:00",
}

# CALL https://api.emploi-store.fr/partenaire/peconnect-statut/v1/statut:
_RESP_USER_STATUS = {"codeStatutIndividu": "1", "libelleStatutIndividu": "Demandeur d’emploi"}

# CALL https://api.emploi-store.fr/partenaire/peconnect-coordonnees/v1/coordonnees:
_RESP_USER_COORDS = {
    "adresse1": None,
    "adresse2": "The cupboard under the stairs",
    "adresse3": None,
    "adresse4": "4, private drive",
    "codePostal": "37700",
    "codeINSEE": "37273",
    "libelleCommune": "LA VILLE AUX DAMES",
    "codePays": "FR",
    "libellePays": "FRANCE",
}

# CALL https://api.emploi-store.fr/partenaire/peconnect-indemnisations/v1/indemnisation:
_RESP_COMPENSATION = {"beneficiairePrestationSolidarite": False, "beneficiaireAssuranceChomage": False}


def _url_for_key(k):
    return f"{pec.API_ESD_BASE_URL}/{k}"


# API DATA: {'given_name': 'Tom', 'family_name': 'Riddle', 'gender': 'male', 'email': 'fred@ikarius.com', 'dateDeNaissance': '1972-03-26T00:00:00+01:00', 'codeStatutIndividu': 1, 'adresse1': None, 'adresse2': None, 'adresse3': None, 'adresse4': '19 RUE CECILE BERGEROT', 'codePostal': '37700', 'codeINSEE': '37273', 'libelleCommune': 'LA VILLE AUX DAMES', 'beneficiairePrestationSolidarite': False, 'beneficiaireAssuranceChomage': False}

_API_KEYS = [
    pec.ESD_COMPENSATION_API,
    pec.ESD_COORDS_API,
    pec.ESD_STATUS_API,
    pec.ESD_BIRTHDATE_API,
    pec.ESD_USERINFO_API,
]


class ExternalDataImportTest(TestCase):
    def _status_ok(self, m):
        # m.get("https://api.emploi-store.fr/partenaire/peconnect-individu/v1/userinfo", text=str(_RESP_USER_INFO))
        m.get(_url_for_key(pec.ESD_USERINFO_API), text=json.dumps(_RESP_USER_INFO))
        m.get(_url_for_key(pec.ESD_BIRTHDATE_API), text=json.dumps(_RESP_USER_BIRTHDATE))
        m.get(_url_for_key(pec.ESD_STATUS_API), text=json.dumps(_RESP_USER_STATUS))
        m.get(_url_for_key(pec.ESD_COORDS_API), text=json.dumps(_RESP_USER_COORDS))
        m.get(_url_for_key(pec.ESD_COMPENSATION_API), text=json.dumps(_RESP_COMPENSATION))

    def _status_partial(self, m):
        self._status_ok(m)
        # Randomly override one or more response with a generic error response
        m.get(_url_for_key(pec.ESD_COMPENSATION_API), text="", status_code=503)

    def _status_failed(self, m):
        for api_k in _API_KEYS:
            m.get(_url_for_key(api_k), text="", status_code=500)

    @requests_mock.Mocker()
    def test_status_ok(self, m):
        user = JobSeekerFactory()

        # Mock all PE APIs
        self._status_ok(m)

        result = import_user_data(user, FOO_TOKEN)
        self.assertEquals(result.status, ExternalDataImport.STATUS_OK)

    @requests_mock.Mocker()
    def test_status_partial(self, m):
        user = JobSeekerFactory()
        self._status_partial(m)
        result = import_user_data(user, FOO_TOKEN)
        self.assertEquals(result.status, ExternalDataImport.STATUS_PARTIAL)

    @requests_mock.Mocker()
    def test_status_failed(self, m):
        user = JobSeekerFactory()
        self._status_failed(m)
        result = import_user_data(user, FOO_TOKEN)
        self.assertEquals(result.status, ExternalDataImport.STATUS_FAILED)


class ExternalUserDataTest(TestCase):
    def test_import_ok(self):
        pass

    def test_import_partial(self):
        pass

    def test_import_failed(self):
        pass
