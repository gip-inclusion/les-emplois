import json

import requests_mock
from django.test import TestCase

import itou.external_data.apis.pe_connect as pec
from itou.users.factories import JobSeekerFactory

from .apis.pe_connect import import_user_pe_data
from .models import ExternalDataImport, RejectedEmailEventData
from .signals import store_rejected_email_event


# Test data import status (All ok, failed, partial)
# Tests are SYNCHRONOUS (because calls to `import_user_pe_data` are)

FOO_TOKEN = "kreacher_token"

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

        result = import_user_pe_data(user, FOO_TOKEN)
        self.assertEqual(result.status, ExternalDataImport.STATUS_OK)

        report = result.report

        # Birthdate is already filled by factory:
        self.assertNotIn(f"User/{user.pk}/birthdate", report.get("fields_updated"))

        self.assertEqual(6 + 1, len(report.get("fields_updated")))  # all the fields + history
        self.assertEqual(12, len(report.get("fields_fetched")))

    @requests_mock.Mocker()
    def test_status_partial(self, m):
        user = JobSeekerFactory()
        _status_partial(m)

        result = import_user_pe_data(user, FOO_TOKEN)
        self.assertEqual(result.status, ExternalDataImport.STATUS_PARTIAL)

        report = result.report
        self.assertTrue(user.has_external_data)
        self.assertNotIn(f"User/{user.pk}/birthdate", report.get("fields_updated"))
        self.assertIn(
            f"JobSeekerExternalData/{user.jobseekerexternaldata.pk}/is_pe_jobseeker", report.get("fields_updated")
        )
        self.assertEqual(5 + 1, len(report.get("fields_updated")))  # fields + history
        self.assertEqual(9, len(report.get("fields_fetched")))
        self.assertEqual(2, len(report.get("fields_failed")))

    @requests_mock.Mocker()
    def test_status_failed(self, m):
        user = JobSeekerFactory()
        _status_failed(m)

        result = import_user_pe_data(user, FOO_TOKEN)
        self.assertEqual(result.status, ExternalDataImport.STATUS_FAILED)

        report = result.report
        self.assertEqual(0, len(report.get("fields_updated")))
        self.assertEqual(0, len(report.get("fields_fetched")))
        self.assertEqual(0, len(report.get("fields_failed")))


class JobSeekerExternalDataTest(TestCase):
    @requests_mock.Mocker()
    def test_import_ok(self, m):
        _status_ok(m)

        user = JobSeekerFactory()

        # Check override of birthdate / of a field
        user.birthdate = None
        user.save()

        result = import_user_pe_data(user, FOO_TOKEN)
        user.refresh_from_db()
        self.assertTrue(user.has_external_data)

        data = user.jobseekerexternaldata

        self.assertFalse(data.has_minimal_social_allowance)
        self.assertTrue(data.is_pe_jobseeker)

        self.assertEqual(user.address_line_1, "4, Privet Drive")
        self.assertEqual(user.address_line_2, "The cupboard under the stairs")
        self.assertEqual(str(user.birthdate), "1970-01-01")

        report = result.report
        self.assertIn(f"User/{user.pk}/birthdate", report.get("fields_updated"))
        self.assertEqual(7 + 1, len(report.get("fields_updated")))  # fields + history
        self.assertEqual(12, len(report.get("fields_fetched")))

        # Just checking birthdate is not overriden
        user = JobSeekerFactory()
        birthdate = user.birthdate

        report = import_user_pe_data(user, FOO_TOKEN).report

        user.refresh_from_db()

        self.assertNotIn(f"User/{user.pk}/birthdate", report.get("fields_updated"))
        self.assertEqual(birthdate, user.birthdate)

    @requests_mock.Mocker()
    def test_import_partial(self, m):
        _status_partial(m)

        user = JobSeekerFactory()
        import_user_pe_data(user, FOO_TOKEN)
        user.refresh_from_db()
        self.assertTrue(user.has_external_data)

        data = user.jobseekerexternaldata

        self.assertIsNone(data.has_minimal_social_allowance)
        self.assertTrue(data.is_pe_jobseeker)

        self.assertEqual(user.address_line_1, "4, Privet Drive")
        self.assertEqual(user.address_line_2, "The cupboard under the stairs")
        self.assertNotEqual(str(user.birthdate), "1970-01-01")

    @requests_mock.Mocker()
    def test_import_failed(self, m):
        _status_failed(m)

        user = JobSeekerFactory()
        import_user_pe_data(user, FOO_TOKEN)
        user.refresh_from_db()
        self.assertTrue(user.has_external_data)

        data = user.jobseekerexternaldata
        self.assertIsNone(data.is_pe_jobseeker)
        self.assertIsNone(data.has_minimal_social_allowance)

    @requests_mock.Mocker()
    def test_has_external_data(self, m):
        _status_ok(m)

        user1 = JobSeekerFactory()
        user2 = JobSeekerFactory()

        import_user_pe_data(user1, FOO_TOKEN)
        user1.refresh_from_db()

        self.assertTrue(user1.has_external_data)
        self.assertFalse(user2.has_external_data)


class MockEmailWebhookEvent:
    def __init__(self, event_type, recipient, reason):
        self.event_type = event_type
        self.recipient = recipient
        self.reject_reason = reason


class AnymailHookTests(TestCase):
    def test_rejected_event(self):
        """
        we store information about rejected events in order to be able to do some analytics about errors
        """
        recipient = "idont@exi.st"
        initial_count = RejectedEmailEventData.objects.count()
        store_rejected_email_event(MockEmailWebhookEvent("rejected", recipient, "invalid"))
        self.assertEqual(RejectedEmailEventData.objects.count(), initial_count + 1)

    def test_accepted_event(self):
        """we do not store information about accepted emails"""
        recipient = "ido@exi.st"
        initial_count = RejectedEmailEventData.objects.count()
        store_rejected_email_event(MockEmailWebhookEvent("accepted", recipient, ""))
        self.assertEqual(RejectedEmailEventData.objects.count(), initial_count)
