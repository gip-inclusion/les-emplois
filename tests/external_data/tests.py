import json

import httpx
import pytest
import respx
from django.conf import settings

import itou.external_data.apis.ft_connect as pec
from itou.external_data.apis.ft_connect import import_user_pe_data
from itou.utils import triggers
from tests.users.factories import JobSeekerFactory


# Test data import status (All ok, failed, partial)
# Tests are SYNCHRONOUS (because calls to `import_user_pe_data` are)

FOO_TOKEN = "kreacher_token"


# CALL https://api.emploi-store.fr/partenaire/peconnect-datenaissance/v1/etat-civil:
_RESP_USER_BIRTHDATE = {
    "codeCivilite": None,
    "libelleCivilite": None,
    "nomPatronymique": None,
    "nomMarital": None,
    "prenom": None,
    "dateDeNaissance": "1970-01-01T00:00:00+01:00",
}

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


def _url_for_key(k):
    return f"{settings.API_ESD['BASE_URL']}/{k}"


_API_KEYS = [
    pec.ESD_COORDS_API,
    pec.ESD_BIRTHDATE_API,
]


def _mock_status_ok():
    respx.get(_url_for_key(pec.ESD_BIRTHDATE_API)).mock(
        httpx.Response(status_code=200, text=json.dumps(_RESP_USER_BIRTHDATE))
    )
    respx.get(_url_for_key(pec.ESD_COORDS_API)).mock(
        httpx.Response(status_code=200, text=json.dumps(_RESP_USER_COORDS))
    )


def _mock_status_partial():
    _mock_status_ok()
    respx.get(_url_for_key(pec.ESD_BIRTHDATE_API)).mock(httpx.Response(text="", status_code=503))


def _mock_status_failed():
    for api_k in _API_KEYS:
        respx.get(_url_for_key(api_k)).mock(httpx.Response(text="", status_code=500))


@pytest.fixture(autouse=True)
def mock_api_esd(settings):
    settings.API_ESD = {
        "BASE_URL": "https://some.auth.domain",
        "AUTH_BASE_URL_PARTENAIRE": "https://some-authentication-domain.fr",
    }


class TestExternalDataImport:
    @respx.mock
    def test_status_ok(self):
        user = JobSeekerFactory()
        old_birthdate = user.jobseeker_profile.birthdate

        # Mock all PE APIs
        _mock_status_ok()

        with triggers.connection_wrapper():
            import_user_pe_data(user, FOO_TOKEN, triggers_context={})

        user.jobseeker_profile.refresh_from_db()
        assert user.jobseeker_profile.birthdate == old_birthdate

    @respx.mock
    def test_status_partial(self):
        user = JobSeekerFactory()
        old_birthdate = user.jobseeker_profile.birthdate

        _mock_status_partial()

        with triggers.connection_wrapper():
            import_user_pe_data(user, FOO_TOKEN, triggers_context={})

        user.jobseeker_profile.refresh_from_db()
        assert user.jobseeker_profile.birthdate == old_birthdate

    @respx.mock
    def test_status_failed(self):
        user = JobSeekerFactory()
        old_birthdate = user.jobseeker_profile.birthdate

        _mock_status_failed()

        import_user_pe_data(user, FOO_TOKEN)

        user.jobseeker_profile.refresh_from_db()
        assert user.jobseeker_profile.birthdate == old_birthdate


class TestJobSeekerExternalData:
    @respx.mock
    def test_import_ok(self):
        _mock_status_ok()

        # Check override of birthdate / of a field
        user = JobSeekerFactory(jobseeker_profile__birthdate=None)

        with triggers.connection_wrapper():
            import_user_pe_data(user, FOO_TOKEN, triggers_context={})
        user.refresh_from_db()

        assert user.address_line_1 == "4, Privet Drive"
        assert user.address_line_2 == "The cupboard under the stairs"
        assert str(user.jobseeker_profile.birthdate) == "1970-01-01"

        # Just checking birthdate is not overridden
        user = JobSeekerFactory()
        birthdate = user.jobseeker_profile.birthdate

        with triggers.connection_wrapper():
            import_user_pe_data(user, FOO_TOKEN, triggers_context={})
        user.refresh_from_db()

        assert birthdate == user.jobseeker_profile.birthdate

    @respx.mock
    def test_import_partial(self):
        _mock_status_partial()

        user = JobSeekerFactory()
        with triggers.connection_wrapper():
            import_user_pe_data(user, FOO_TOKEN, triggers_context={})
        user.refresh_from_db()

        assert user.address_line_1 == "4, Privet Drive"
        assert user.address_line_2 == "The cupboard under the stairs"
        assert str(user.jobseeker_profile.birthdate) != "1970-01-01"

    @respx.mock
    def test_import_address_if_missing(self):
        _mock_status_ok()

        # Check override of birthdate / of a field
        user = JobSeekerFactory(jobseeker_profile__birthdate=None, with_address=True)
        assert user.address_line_2 == ""
        old_address_one_line = user.address_on_one_line

        with triggers.connection_wrapper():
            import_user_pe_data(user, FOO_TOKEN, triggers_context={})
        user.refresh_from_db()

        assert user.address_on_one_line == old_address_one_line
        assert user.address_line_2 == ""
        assert str(user.jobseeker_profile.birthdate) == "1970-01-01"

        # Just checking birthdate is not overridden
        user = JobSeekerFactory()
        birthdate = user.jobseeker_profile.birthdate

        with triggers.connection_wrapper():
            import_user_pe_data(user, FOO_TOKEN, triggers_context={})
        user.refresh_from_db()

        assert birthdate == user.jobseeker_profile.birthdate
