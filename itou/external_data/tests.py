import requests_mock
from django.test import TestCase
from itou.users.factories import JobSeekerFactory
from .apis.pe_connect import import_user_data
from .models import ExternalDataImport

# Test data import status (All ok, failed, partial)

# Mock PE connect endpoints

FOO_TOKEN = "foo_token"

# CALL https://api.emploi-store.fr/partenaire/peconnect-individu/v1/userinfo: 
_RESP_USER_INFO = {'given_name': 'FREDERIC', 'family_name': 'VERGEZ', 'gender': 'male', 'idIdentiteExterne': '46533ae7-da92-4614-9d9b-12c47a5d14c9', 'email': 'fred@ikarius.com', 'sub': '46533ae7-da92-4614-9d9b-12c47a5d14c9', 'updated_at': 0}

# CALL https://api.emploi-store.fr/partenaire/peconnect-datenaissance/v1/etat-civil: 
_RESP_USER_BIRTHDATE = {'codeCivilite': None, 'libelleCivilite': None, 'nomPatronymique': None, 'nomMarital': None, 'prenom': None, 'dateDeNaissance': '1972-03-26T00:00:00+01:00'}

# CALL https://api.emploi-store.fr/partenaire/peconnect-statut/v1/statut: 
_RESP_USER_STATUS = {'codeStatutIndividu': '1', 'libelleStatutIndividu': 'Demandeur d’emploi'}

# CALL https://api.emploi-store.fr/partenaire/peconnect-coordonnees/v1/coordonnees: 
_RESP_USER_COORDS = {'adresse1': None, 'adresse2': None, 'adresse3': None, 'adresse4': '19 RUE CECILE BERGEROT', 'codePostal': '37700', 'codeINSEE': '37273', 'libelleCommune': 'LA VILLE AUX DAMES', 'codePays': 'FR', 'libellePays': 'FRANCE'}

# CALL https://api.emploi-store.fr/partenaire/peconnect-indemnisations/v1/indemnisation: 
_RESP_COMPENSATION = {'beneficiairePrestationSolidarite': False, 'beneficiaireAssuranceChomage': False}

# API DATA: {'given_name': 'FREDERIC', 'family_name': 'VERGEZ', 'gender': 'male', 'email': 'fred@ikarius.com', 'dateDeNaissance': '1972-03-26T00:00:00+01:00', 'codeStatutIndividu': 1, 'adresse1': None, 'adresse2': None, 'adresse3': None, 'adresse4': '19 RUE CECILE BERGEROT', 'codePostal': '37700', 'codeINSEE': '37273', 'libelleCommune': 'LA VILLE AUX DAMES', 'beneficiairePrestationSolidarite': False, 'beneficiaireAssuranceChomage': False}


class ExternalDataImportTest(TestCase):

    @requests_mock.Mocker()
    def setUp(self, m):
        m.get("https://api.emploi-store.fr/partenaire/peconnect-individu/v1/userinfo", text=str(_RESP_USER_INFO))

    def test_status_ok(self):
        user = JobSeekerFactory()
        result = import_user_data(user, FOO_TOKEN)
        print(result)
        self.assertEquals(result.status, ExternalDataImport.STATUS_OK)

    def test_status_partial(self):
        pass

    def test_status_failed(self):
        pass


class ExternalUserDataTest(TestCase):

    def test_import_ok(self):
        pass

    def test_import_partial(self):
        pass

    def test_import_failed(self):
        pass
