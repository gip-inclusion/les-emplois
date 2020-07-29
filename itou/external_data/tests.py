import json
import random

import requests_mock
from django.test import TestCase

import itou.external_data.apis.pe_connect as pec
from itou.users.factories import JobSeekerFactory

from .apis.pe_connect import import_user_data
from .models import ExternalDataImport, ExternalUserData


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
    "adresse4": "4, Privet Drive",
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


_API_KEYS = [
    pec.ESD_COMPENSATION_API,
    pec.ESD_COORDS_API,
    pec.ESD_STATUS_API,
    pec.ESD_BIRTHDATE_API,
    pec.ESD_USERINFO_API,
]


def _status_ok(m):
    m.get(_url_for_key(pec.ESD_USERINFO_API), text=json.dumps(_RESP_USER_INFO))
    m.get(_url_for_key(pec.ESD_BIRTHDATE_API), text=json.dumps(_RESP_USER_BIRTHDATE))
    m.get(_url_for_key(pec.ESD_STATUS_API), text=json.dumps(_RESP_USER_STATUS))
    m.get(_url_for_key(pec.ESD_COORDS_API), text=json.dumps(_RESP_USER_COORDS))
    m.get(_url_for_key(pec.ESD_COMPENSATION_API), text=json.dumps(_RESP_COMPENSATION))


def _status_partial(m):
    _status_ok(m)
    m.get(_url_for_key(pec.ESD_COMPENSATION_API), text="", status_code=503)
    m.get(_url_for_key(pec.ESD_BIRTHDATE_API), text="", status_code=503)


def _status_failed(m):
    for api_k in _API_KEYS:
        m.get(_url_for_key(api_k), text="", status_code=500)


class ExternalDataImportTest(TestCase):
    @requests_mock.Mocker()
    def test_status_ok(self, m):
        user = JobSeekerFactory()

        # Mock all PE APIs
        _status_ok(m)

        result = import_user_data(user, FOO_TOKEN)
        self.assertEquals(result.status, ExternalDataImport.STATUS_OK)

    @requests_mock.Mocker()
    def test_status_partial(self, m):
        user = JobSeekerFactory()
        _status_partial(m)
        result = import_user_data(user, FOO_TOKEN)
        self.assertEquals(result.status, ExternalDataImport.STATUS_PARTIAL)

    @requests_mock.Mocker()
    def test_status_failed(self, m):
        user = JobSeekerFactory()
        _status_failed(m)
        result = import_user_data(user, FOO_TOKEN)
        self.assertEquals(result.status, ExternalDataImport.STATUS_FAILED)


# API DATA: {'given_name': 'Tom', 'family_name': 'Riddle', 'gender': 'male', 'email': 'fred@ikarius.com', 'dateDeNaissance': '1972-03-26T00:00:00+01:00', 'codeStatutIndividu': 1, 'adresse1': None, 'adresse2': None, 'adresse3': None, 'adresse4': '19 RUE CECILE BERGEROT', 'codePostal': '37700', 'codeINSEE': '37273', 'libelleCommune': 'LA VILLE AUX DAMES', 'beneficiairePrestationSolidarite': False, 'beneficiaireAssuranceChomage': False}


class ExternalUserDataTest(TestCase):
    @requests_mock.Mocker()
    def test_import_ok(self, m):
        _status_ok(m)

        user = JobSeekerFactory()

        # Check override of birthdate
        user.birthdate = None

        result = import_user_data(user, FOO_TOKEN)
        self.assertTrue(result.externaluserdata_set.exists())

        data = ExternalUserData.user_data_to_dict(user)

        # Key/values
        self.assertFalse(data.has_minimal_social_allowance)
        self.assertTrue(data.is_pe_jobseeker)

        # Inserted into model
        self.assertEquals(user.address_line_1, "4, Privet Drive")
        self.assertEquals(str(user.birthdate), "1970-01-01 00:00:00+01:00")

    @requests_mock.Mocker()
    def test_import_partial(self, m):
        _status_partial(m)

        user = JobSeekerFactory()
        result = import_user_data(user, FOO_TOKEN)
        self.assertTrue(result.externaluserdata_set.exists())

        data = ExternalUserData.user_data_to_dict(user)

        # Key/values
        self.assertIsNone(data.has_minimal_social_allowance)
        self.assertTrue(data.is_pe_jobseeker)

        # Inserted into model
        self.assertEquals(user.address_line_1, "4, Privet Drive")
        self.assertNotEquals(str(user.birthdate), "1970-01-01 00:00:00+01:00")

    @requests_mock.Mocker()
    def test_import_failed(self, m):
        _status_failed(m)

        user = JobSeekerFactory()
        result = import_user_data(user, FOO_TOKEN)
        self.assertFalse(result.externaluserdata_set.exists())
