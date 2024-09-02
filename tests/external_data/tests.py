import json

import httpx
import pytest
import respx
from django.conf import settings

import itou.external_data.apis.pe_connect as pec
from itou.external_data.apis.pe_connect import import_user_pe_data
from itou.external_data.models import ExternalDataImport, RejectedEmailEventData
from itou.external_data.signals import store_rejected_email_event
from itou.users.enums import IdentityProvider
from tests.users.factories import JobSeekerFactory


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
    return f"{settings.API_ESD['BASE_URL']}/{k}"


_API_KEYS = [
    pec.ESD_COMPENSATION_API,
    pec.ESD_COORDS_API,
    pec.ESD_STATUS_API,
    pec.ESD_BIRTHDATE_API,
    pec.ESD_USERINFO_API,
]


def _mock_status_ok():
    respx.get(_url_for_key(pec.ESD_USERINFO_API)).mock(
        httpx.Response(status_code=200, text=json.dumps(_RESP_USER_INFO))
    )
    respx.get(_url_for_key(pec.ESD_BIRTHDATE_API)).mock(
        httpx.Response(status_code=200, text=json.dumps(_RESP_USER_BIRTHDATE))
    )
    respx.get(_url_for_key(pec.ESD_STATUS_API)).mock(
        httpx.Response(status_code=200, text=json.dumps(_RESP_USER_STATUS))
    )
    respx.get(_url_for_key(pec.ESD_COORDS_API)).mock(
        httpx.Response(status_code=200, text=json.dumps(_RESP_USER_COORDS))
    )
    respx.get(_url_for_key(pec.ESD_COMPENSATION_API)).mock(
        httpx.Response(status_code=200, text=json.dumps(_RESP_COMPENSATION))
    )


def _mock_status_partial():
    _mock_status_ok()
    respx.get(_url_for_key(pec.ESD_COMPENSATION_API)).mock(httpx.Response(text="", status_code=503))
    respx.get(_url_for_key(pec.ESD_BIRTHDATE_API)).mock(httpx.Response(text="", status_code=503))


def _mock_status_failed():
    for api_k in _API_KEYS:
        respx.get(_url_for_key(api_k)).mock(httpx.Response(text="", status_code=500))


@pytest.fixture(autouse=True)
def mock_api_esd(settings):
    settings.API_ESD = {
        "BASE_URL": "https://some.auth.domain",
        "AUTH_BASE_URL": "https://some-authentication-domain.fr",
    }


class TestExternalDataImport:
    @respx.mock
    def test_status_ok(self):
        user = JobSeekerFactory()

        # Mock all PE APIs
        _mock_status_ok()

        result = import_user_pe_data(user, FOO_TOKEN)
        assert result.status == ExternalDataImport.STATUS_OK

        report = result.report

        # Birthdate is already filled by factory:
        assert f"User/{user.pk}/birthdate" not in report.get("fields_updated")

        assert 6 + 1 == len(report.get("fields_updated"))  # all the fields + history
        assert 12 == len(report.get("fields_fetched"))

    @respx.mock
    def test_status_partial(self):
        user = JobSeekerFactory()
        _mock_status_partial()

        result = import_user_pe_data(user, FOO_TOKEN)
        assert result.status == ExternalDataImport.STATUS_PARTIAL

        report = result.report
        assert user.has_external_data
        assert f"User/{user.pk}/birthdate" not in report.get("fields_updated")
        assert f"JobSeekerExternalData/{user.jobseekerexternaldata.pk}/is_pe_jobseeker" in report.get("fields_updated")
        assert 5 + 1 == len(report.get("fields_updated"))  # fields + history
        assert 9 == len(report.get("fields_fetched"))
        assert 2 == len(report.get("fields_failed"))

    @respx.mock
    def test_status_failed(self):
        user = JobSeekerFactory()
        _mock_status_failed()

        result = import_user_pe_data(user, FOO_TOKEN)
        assert result.status == ExternalDataImport.STATUS_FAILED

        report = result.report
        assert 0 == len(report.get("fields_updated"))
        assert 0 == len(report.get("fields_fetched"))
        assert 0 == len(report.get("fields_failed"))


class TestJobSeekerExternalData:
    @respx.mock
    def test_import_ok(self):
        _mock_status_ok()

        # Check override of birthdate / of a field
        user = JobSeekerFactory(jobseeker_profile__birthdate=None)

        result = import_user_pe_data(user, FOO_TOKEN)
        user.refresh_from_db()
        assert user.has_external_data

        data = user.jobseekerexternaldata

        assert not data.has_minimal_social_allowance
        assert data.is_pe_jobseeker

        assert user.address_line_1 == "4, Privet Drive"
        assert user.address_line_2 == "The cupboard under the stairs"
        assert str(user.jobseeker_profile.birthdate) == "1970-01-01"

        report = result.report
        assert f"JobSeekerProfile/{user.pk}/birthdate" in report.get("fields_updated")
        assert 7 + 1 == len(report.get("fields_updated"))  # fields + history
        assert 12 == len(report.get("fields_fetched"))

        # Just checking birthdate is not overriden
        user = JobSeekerFactory()
        birthdate = user.jobseeker_profile.birthdate

        report = import_user_pe_data(user, FOO_TOKEN).report

        user.refresh_from_db()

        assert f"JobSeekerProfile/{user.pk}/birthdate" not in report.get("fields_updated")
        assert birthdate == user.jobseeker_profile.birthdate
        assert user.external_data_source_history[0]["source"] == IdentityProvider.PE_CONNECT.value

    @respx.mock
    def test_import_partial(self):
        _mock_status_partial()

        user = JobSeekerFactory()
        import_user_pe_data(user, FOO_TOKEN)
        user.refresh_from_db()
        assert user.has_external_data

        data = user.jobseekerexternaldata

        assert data.has_minimal_social_allowance is None
        assert data.is_pe_jobseeker

        assert user.address_line_1 == "4, Privet Drive"
        assert user.address_line_2 == "The cupboard under the stairs"
        assert str(user.jobseeker_profile.birthdate) != "1970-01-01"
        assert user.external_data_source_history[0]["source"] == IdentityProvider.PE_CONNECT.value

    @respx.mock
    def test_import_failed(self):
        _mock_status_failed()

        user = JobSeekerFactory()
        import_user_pe_data(user, FOO_TOKEN)
        user.refresh_from_db()
        assert user.has_external_data

        data = user.jobseekerexternaldata
        assert data.is_pe_jobseeker is None
        assert data.has_minimal_social_allowance is None

    @respx.mock
    def test_has_external_data(self):
        _mock_status_ok()

        user1 = JobSeekerFactory()
        user2 = JobSeekerFactory()

        import_user_pe_data(user1, FOO_TOKEN)
        user1.refresh_from_db()

        assert user1.has_external_data
        assert not user2.has_external_data


class MockEmailWebhookEvent:
    def __init__(self, event_type, recipient, reason):
        self.event_type = event_type
        self.recipient = recipient
        self.reject_reason = reason


class TestAnymailHook:
    def test_rejected_event(self):
        """
        we store information about rejected events in order to be able to do some analytics about errors
        """
        recipient = "idont@exi.st"
        initial_count = RejectedEmailEventData.objects.count()
        store_rejected_email_event(MockEmailWebhookEvent("rejected", recipient, "invalid"))
        assert RejectedEmailEventData.objects.count() == initial_count + 1

    def test_accepted_event(self):
        """we do not store information about accepted emails"""
        recipient = "ido@exi.st"
        initial_count = RejectedEmailEventData.objects.count()
        store_rejected_email_event(MockEmailWebhookEvent("accepted", recipient, ""))
        assert RejectedEmailEventData.objects.count() == initial_count
