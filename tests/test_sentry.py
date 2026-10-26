import copy
import json
import logging
import re
import urllib.parse

import httpx
import pytest
import respx
import sentry_sdk
from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseServerError
from django.urls import include, path
from rest_framework.permissions import IsAuthenticated
from rest_framework.test import APIClient
from rest_framework.views import APIView
from sentry_sdk.utils import AnnotatedValue, iter_event_frames

from config.sentry import (
    PII_SCRUBBING_FAILED,
    SENSITIVE_API_PARAMETERS,
    _is_sensitive_key,
    scrub_sensitive_data,
)
from itou.api.auth import ServiceTokenAuthentication
from itou.api.models import ServiceToken
from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.tasks import certify_criterion_with_api_particulier
from itou.nexus.enums import Service
from itou.users.enums import UserKind
from itou.utils.apis import api_particulier
from itou.utils.apis.france_travail_agent import get_user_data
from itou.utils.apis.geocoding import call_ban_geocoding_api
from itou.utils.apis.pole_emploi import Endpoints, PoleEmploiAPIException, PoleEmploiRoyaumePartenaireApiClient
from itou.utils.mocks.pole_emploi import RESPONSES, ResponseKind
from itou.utils.redaction import ANONYMOUS_USER_ID, REDACTED
from tests.companies.factories import CompanyMembershipFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.users.factories import JobSeekerFactory


pytestmark = pytest.mark.usefixtures("sentry", "clean_sentry_scope")

SDK_FILTERED = AnnotatedValue.substituted_because_contains_sensitive_data().value

# The SDK's EventScrubber substitutes its own placeholder, before_send substitutes ours.
REDACTION_MARKERS = (REDACTED, SDK_FILTERED)

# An API parameter reaches the event raw, in a request kwarg or an exception message (`prenoms[]`),
# or percent-encoded, in the query string of a URL (`prenoms%5B%5D`)
API_PARAMETER_SPELLINGS = frozenset(
    spelling for name in SENSITIVE_API_PARAMETERS for spelling in (name, urllib.parse.quote(name, safe=""))
)


@pytest.fixture(name="clean_sentry_scope")
def clean_sentry_scope_fixture():
    """Isolate the test from the breadcrumbs and event processors left behind by the previous ones.

    The SDK keeps its scopes for the whole process, and an event is built from the
    breadcrumbs of the isolation scope *and* of the current one. Without forking
    both, every HTTP request and INFO log of the test suite ends up in the events
    captured here. Forking means the buffers can be emptied without affecting the
    rest of the run.
    """
    with sentry_sdk.isolation_scope() as isolation_scope, sentry_sdk.new_scope() as scope:
        for forked_scope in (isolation_scope, scope):
            forked_scope.clear()  # clear the entire scope, including breadcrumbs, tags, extras, etc.
            # `clear()` keeps the event processors. The test client bypasses the per-request fork
            # of the SDK, so those added by `sentry_user_id` in earlier tests are still there
            forked_scope._event_processors.clear()
        yield


@pytest.fixture(name="prepare_event_spy")
def prepare_event_spy_fixture(mocker):
    return mocker.spy(sentry_sdk.client._Client, "_prepare_event")


@pytest.fixture(name="captured_event")
def captured_event_fixture(prepare_event_spy):
    """Return the one event the test captured."""

    def captured_event():
        assert prepare_event_spy.call_count == 1
        return prepare_event_spy.spy_return

    return captured_event


def event_payload(event):
    """Serialize an event, minus the source lines Sentry attaches to every frame.

    Those lines quote our own source, which names the sensitive keys verbatim (`profile.nir`,
    `job_seeker.first_name`, …), and no scan can tell them apart from a leaked value. They are
    checked-in code, never personal data.

    Values the SDK scrubbed are rendered as their placeholder: `AnnotatedValue` is not JSON
    serializable, and its repr would hide that placeholder behind an object address, which no
    assertion below could tell from a leak.
    """
    event = copy.deepcopy(event)
    for frame in iter_event_frames(event):
        for source_key in ["pre_context", "context_line", "post_context"]:
            frame.pop(source_key, None)
    # `ensure_ascii` would escape the accents of a French name, hiding it from the scans below.
    return json.dumps(
        event,
        default=lambda value: value.value if isinstance(value, AnnotatedValue) else repr(value),
        ensure_ascii=False,
    )


def assert_sensitive_values_are_redacted(payload):
    """Assert every API parameter found in the event is followed by a redaction marker.

    The birth date and the birth place are digits, which collide with unrelated numbers of
    the event (package versions, event ids, …), so they cannot be looked up as-is: they are
    checked through the key that carries them.

    Only `SENSITIVE_API_PARAMETERS` are looked up this way. The names and fragments such as
    `first_name` are ordinary words that the event mentions without carrying a value (a Django
    field list, a line of our own source), and `SENSITIVE_API_RESPONSE_FIELDS` never appear in
    a request, so both are checked by value in the tests instead.
    """
    # Longest first: "prenom" must not match where "prenoms%5B%5D" is meant.
    spellings = sorted(API_PARAMETER_SPELLINGS, key=lambda spelling: (-len(spelling), spelling))
    keys = "|".join(re.escape(spelling) for spelling in spellings)
    # A key is only interesting when a value follows it.
    for match in re.finditer(rf"\b(?:{keys})(?=[=:'\"\\])(.{{0,32}})", payload):
        # What separates a key from its value depends on where it appears: "=" in a query
        # string, "': '" in the repr of the params dict, escaped quotes in nested JSON…
        value = match.group(1).lstrip("\\'\": =")
        assert value.startswith(REDACTION_MARKERS), f"PII in the Sentry event: {match.group(0)}"


def assert_no_pii(payload, *values):
    """Assert that none of `values` is in the event, whatever its case, nor any API parameter value."""
    assert '"vars"' in payload  # guard against a false negative
    for value in values:
        assert value.upper() not in payload.upper()
    assert_sensitive_values_are_redacted(payload)


def test_before_send_http_breadcrumb_sanitizer(respx_mock, captured_event):
    url = "https://example.com/"
    params = {
        "foobar": 34,
        "nomNaissance": "Martin",
        "prenoms[]": "Jean",
        "jourDateNaissance": 12,
        "moisDateNaissance": 5,
        "anneeDateNaissance": 1980,
    }
    respx_mock.get(url, params=params).mock(return_value=httpx.Response(418))
    httpx.get(url, params=params)
    sentry_sdk.capture_message("Test message")
    event = captured_event()
    assert event["message"] == "Test message"
    http_breadcrumbs = [breadcrumb for breadcrumb in event["breadcrumbs"]["values"] if breadcrumb["type"] == "http"]
    [http_breadcrumb] = http_breadcrumbs
    # Every value goes, `foobar` included: an outgoing query string is redacted whatever its
    # parameters are, so a client added tomorrow needs no entry in any list
    assert http_breadcrumb["data"]["http.query"] == (
        "foobar=_REDACTED_&nomNaissance=_REDACTED_&prenoms%5B%5D=_REDACTED_"
        "&jourDateNaissance=_REDACTED_&moisDateNaissance=_REDACTED_&anneeDateNaissance=_REDACTED_"
    )


@pytest.fixture(name="certifiable_diagnosis")
def certifiable_diagnosis_fixture():
    return IAEEligibilityDiagnosisFactory(
        certifiable=True,
        criteria_kinds=[AdministrativeCriteriaKind.RSA],
        job_seeker__first_name="Jean-Michel",
        job_seeker__last_name="Tardiveau",
        # born in France also sends the birth place to the API
        job_seeker__born_outside_france=False,
        job_seeker__born_in_france=True,
    )


@pytest.mark.usefixtures("api_particulier_settings")
@pytest.mark.parametrize(
    "mock_kwargs,exception",
    [
        pytest.param(
            {"return_value": httpx.Response(502, text="Bad Gateway (non-JSON response)")},
            httpx.HTTPStatusError,
            id="down",
        ),
        pytest.param({"side_effect": httpx.ConnectTimeout("timed out")}, httpx.TransportError, id="unreachable"),
    ],
)
def test_no_pii_in_event_when_api_particulier_fails(
    respx_mock, certifiable_diagnosis, captured_event, mock_kwargs, exception
):
    """The identity of the job seeker must not reach Sentry when API Particulier fails.

    An error response puts the URL, query string included, in the message of the exception. A
    transport error raises from inside httpx, whose own frames hold the query parameters: nothing
    the client does can scrub those frames, so this is the case the per-call-site redaction in
    api_particulier._request cannot cover.
    """
    criterion = certifiable_diagnosis.selected_administrative_criteria.get()
    endpoint = api_particulier.ENDPOINTS[AdministrativeCriteriaKind.RSA]
    respx_mock.get(settings.API_PARTICULIER_BASE_URL + endpoint).mock(**mock_kwargs)

    # This is what the Huey integration does with a failing task
    try:
        certify_criterion_with_api_particulier(criterion)
    except exception:
        sentry_sdk.capture_exception()
    else:
        pytest.fail("API Particulier errors should bubble up so that the task is retried.")

    job_seeker = certifiable_diagnosis.job_seeker
    assert_no_pii(event_payload(captured_event()), job_seeker.first_name, job_seeker.last_name)


@respx.mock
def test_no_pii_in_event_when_france_travail_fails(captured_event):
    """France Travail receives the NIR, which _request holds as a local while it raises."""
    respx.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").respond(
        200, json={"token_type": "foo", "access_token": "batman", "expires_in": 3600}
    )
    respx.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
        500, json={"message": "Internal Server Error"}
    )
    job_seeker = JobSeekerFactory(first_name="Jean-Michel", last_name="Tardiveau")
    profile = job_seeker.jobseeker_profile
    api_client = PoleEmploiRoyaumePartenaireApiClient("https://pe.fake", "https://auth.fr", "foobar", "pe-secret")

    try:
        api_client.recherche_individu_certifie(
            job_seeker.first_name, job_seeker.last_name, profile.birthdate, profile.nir
        )
    except PoleEmploiAPIException:
        sentry_sdk.capture_exception()
    else:
        pytest.fail("A 500 from France Travail should raise.")

    assert_no_pii(event_payload(captured_event()), profile.nir, job_seeker.first_name, job_seeker.last_name)


@pytest.fixture(name="france_travail_agent_api")
def france_travail_agent_api_fixture(settings, respx_mock):
    """Mock the France Travail agent API up to the call that fails.

    Only the routes actually reached are registered: `respx_mock` asserts they all are.
    """
    settings.API_ESD = {
        "BASE_URL": "https://pe.fake",
        "AUTH_BASE_URL_AGENT": "https://auth.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
    respx_mock.post(f"{settings.API_ESD['AUTH_BASE_URL_AGENT']}/connexion/oauth2/access_token?realm=%2Fagent").respond(
        200, json={"token_type": "Bearer", "access_token": "Catwoman", "expires_in": 1499}
    )
    respx_mock.post(f"{settings.API_ESD['BASE_URL']}{Endpoints.RECHERCHER_USAGER_NUMERO_FRANCE_TRAVAIL}").respond(
        200, json=RESPONSES[Endpoints.RECHERCHER_USAGER_NUMERO_FRANCE_TRAVAIL][ResponseKind.CERTIFIED]
    )
    respx_mock.get(settings.API_ESD["BASE_URL"] + Endpoints.INFORMATIONS_ADMINISTRATIVES_USAGER).respond(
        200, json=RESPONSES[Endpoints.INFORMATIONS_ADMINISTRATIVES_USAGER][ResponseKind.CERTIFIED]
    )
    # The identity is already fetched and parsed when this one blows up
    respx_mock.get(settings.API_ESD["BASE_URL"] + Endpoints.STATUT_USAGER).respond(500, json={"message": "Boom"})


@pytest.mark.usefixtures("france_travail_agent_api")
def test_no_pii_in_event_when_france_travail_user_data_fails(captured_event):
    """France Travail answers with the identity of the job seeker, under its own field names.

    When a call fails, `get_user_data` logs the error, and the logging integration sends it to
    Sentry with the local variables of every frame of the traceback. Two of those locals are a
    problem:

    * the raw API response: its keys (`etatCivil`, `prenom`, …) are not request parameters,
      so the list of sensitive keys does not cover them.
    * the parsed `AdministrativeData`: it is serialized as a string (its repr), and a string
      has no keys left to match, so key based scrubbing cannot redact what is inside.

    That is why this test looks for the values themselves instead of relying on key names.
    """
    ft_id = "ft-id-of-jean-michel"

    assert get_user_data(ft_id) is None

    identity = RESPONSES[Endpoints.INFORMATIONS_ADMINISTRATIVES_USAGER][ResponseKind.CERTIFIED]
    address = identity["adresses"][0]
    assert_no_pii(
        event_payload(captured_event()),
        ft_id,  # what every frame down to the failing call holds as a local
        identity["etatCivil"]["nom"],
        identity["etatCivil"]["prenom"],
        identity["etatCivil"]["nir"],
        identity["emails"][0]["adresseEmail"],
        identity["telephones"][0]["numeroTelephone"],
        address["numeroTypeLibelleVoie"],
        address["complementAdresse"],
        address["libelleCommune"],
    )


def test_no_pii_in_event_when_geocoding_fails(respx_mock, settings, captured_event):
    """The home address of the job seeker travels in the query string of the geocoding call.

    It leaks twice over: through the `HttpxIntegration` breadcrumb, whose `http.query` is the
    query string itself, and through the INFO log below it, whose message quotes the whole URL.
    Neither name appears in the list of sensitive parameters (q and postcode do not look sensitive),
    so these two are redacted whatever their value.
    """
    settings.API_GEOPF_BASE_URL = "http://ban-api"
    address, post_code = "112 rue de la Croix-Nivert", "75015"
    respx_mock.get("http://ban-api/geocodage/search/").respond(500, text="Internal Server Error")

    assert call_ban_geocoding_api(address, post_code=post_code) is None
    # Breadcrumbs are only sent attached to an event: capture one so the ones recorded above show up in the payload.
    sentry_sdk.capture_message("Test message")

    payload = event_payload(captured_event())
    assert "ban-api" in payload  # guard against a false negative
    for pii in [address, post_code, "rue+de+la+Croix-Nivert"]:
        assert pii not in payload


def test_our_own_query_string_stays_readable():
    """Blanket redaction is for outgoing calls: the filters of our own pages are worth keeping.

    Sentry stores our request as a `url` without the query and a `query_string` without the
    host, so neither looks like the outgoing URL the blanket rule matches. What is left there
    is the denylist, on parameter names.
    """
    event = {
        "request": {
            "url": "https://emplois.inclusion.beta.gouv.fr/admin/users/user/",
            "query_string": "page=2&status=new&nir=180081380021",
        }
    }

    scrubbed = scrub_sensitive_data(event)

    assert scrubbed["request"]["query_string"] == f"page=2&status=new&nir={REDACTED}"


def test_contact_details_are_scrubbed_wherever_they_are_keyed():
    """The RDV-Insertion invitation payload, which `capture_exception` serializes as a frame local."""
    data = {
        "user": {
            "first_name": "Jean-Michel",
            "last_name": "Tardiveau",
            "title": "monsieur",
            "role": "demandeur",
            "email": "jean-michel@example.com",
            "phone_number": "0612345678",
            "birth_date": "25/07/1979",
            "address": "112 rue de la Croix-Nivert, 75015 Paris",
        }
    }

    scrubbed = scrub_sensitive_data(data)["user"]

    assert scrubbed == {
        "first_name": REDACTED,
        "last_name": REDACTED,
        "title": "monsieur",  # not identifying on its own, and it tells the invitation apart
        "role": "demandeur",
        "email": REDACTED,
        "phone_number": REDACTED,
        "birth_date": REDACTED,
        "address": REDACTED,
    }


def test_degraded_event_when_scrubbing_fails(mocker, captured_event):
    """A crash in the scrubber must not leak the event, nor silence the alert."""
    mocker.patch("config.sentry.scrub_sensitive_data", side_effect=RuntimeError("boom for jean-michel@example.com"))

    try:
        raise ValueError("original error")
    except ValueError:
        sentry_sdk.capture_exception()

    event = captured_event()
    assert event["message"] == PII_SCRUBBING_FAILED
    assert event["tags"]["pii_scrubbing"] == "failed"
    assert event["tags"]["exception_type"] == "ValueError"
    # Why the scrubber failed, but not its message, which can quote what it was scrubbing
    assert event["tags"]["pii_scrubbing_error"] == "RuntimeError"
    assert event["tags"]["pii_scrubbing_location"].startswith("sentry.py:")
    # Grouped by the original error, so that muting one issue does not mute them all
    assert event["fingerprint"] == ["pii-scrubbing-failed", "ValueError"]
    assert event["event_id"]  # `capture_event` reads it to build the envelope header
    payload = event_payload(event)
    # The stack frames are the whole point: they are what carries the local variables.
    assert '"vars"' not in payload
    assert "jean-michel" not in payload


def test_last_resort_event_when_the_degraded_event_fails_too(mocker, captured_event):
    """The fallback of the fallback must still be an event Sentry can send."""
    mocker.patch("config.sentry.scrub_sensitive_data", side_effect=RuntimeError("boom"))
    mocker.patch("config.sentry.degraded_event", side_effect=RuntimeError("boom too"))
    transport = mocker.patch.object(sentry_sdk.get_client(), "transport")

    try:
        raise ValueError("original error")
    except ValueError:
        event_id = sentry_sdk.capture_exception()

    assert captured_event() == {
        "event_id": event_id,
        "message": PII_SCRUBBING_FAILED,
        "level": "error",
        "tags": {"pii_scrubbing": "failed"},
    }
    # Without `event_id`, `capture_event` raises while building the envelope header and
    # `capture_internal_exceptions` swallows it: the alert would be lost just as silently.
    assert transport.capture_envelope.call_count == 1


@pytest.mark.parametrize(
    "key,expected",
    [
        # Personal fields, whether a list names them or only a fragment matches them
        ("nomNaissance", True),
        ("date_naissance", True),
        ("birth_place", True),  # the field a list of key names kept missing
        ("birth_country_id", True),
        ("adresseEmail", True),
        ("numeroTelephone", True),
        ("address_line_1", True),
        ("contact_phone", True),
        # The France Travail identifier, under each of its names
        ("pole_emploi_id", True),
        ("job_seeker_france_travail_id", True),
        ("ft_id", True),
        # Ordinary words a fragment must not swallow, and the exceptions to it
        ("template_name", False),
        ("model_name", False),
        ("draft_id", False),
        ("denominationUniteLegale", False),
        ("siret", False),
        ("email_id", False),
        ("lack_of_nir_reason", False),
        ("lack_of_pole_emploi_id_reason", False),
        ("pe_obfuscated_nir", False),
        ("require_phone_interview", False),
    ],
)
def test_is_sensitive_key(key, expected):
    assert _is_sensitive_key(key) is expected


def test_log_event_keeps_its_message_template(captured_event):
    """Sentry groups the events of a log without a traceback by their message template.

    The console handler redacts its own output and leaves the record alone, so the Sentry logging
    integration, which reads the same record, still gets the template and its arguments. A redacted
    message would split the events into one issue per URL.
    """
    url = httpx.URL("https://particulier.api.gouv.fr/v3/dss/identite?nomNaissance=TARDIVEAU")

    logging.getLogger("itou.utils.apis.some_client").error("Request failed for %s", url)

    event = captured_event()
    assert event["logentry"]["message"] == "Request failed for %s"
    assert "TARDIVEAU" not in event_payload(event)


@login_not_required
def boom_view(request):
    raise RuntimeError("boom")


class BoomAPIView(APIView):
    authentication_classes = [ServiceTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        raise RuntimeError("boom")


@login_not_required
def boom_error_view(request):
    # The real 500 page renders `layout/base.html`, which this URLconf has no context for.
    return HttpResponseServerError("boom")


# `ROOT_URLCONF` points at this module in the tests below, which need a view that fails. The real
# URLs are included as well: some middlewares reverse them on every request, such as
# `itou.audit_trail.middleware.browser_id_cookie`.
urlpatterns = [
    path("boom", boom_view),
    path("boom-api", BoomAPIView.as_view()),
    path("", include("config.urls")),
]
handler500 = boom_error_view


@pytest.fixture(name="failing_urlconf")
def failing_urlconf_fixture(settings, client):
    settings.ROOT_URLCONF = __name__
    # Without this, the test client re-raises the exception before the assertions run
    client.raise_request_exception = False


@pytest.mark.usefixtures("failing_urlconf")
def test_only_the_user_id_is_reported_for_an_authenticated_user(client, captured_event):
    """An error names the user by ID, never by identity."""
    job_seeker = JobSeekerFactory(first_name="Jean-Michel", last_name="Tardiveau")
    client.force_login(job_seeker)

    client.get("/boom")

    event = captured_event()
    assert event["user"] == {"id": str(job_seeker.pk)}
    payload = event_payload(event)
    for pii in [job_seeker.email, job_seeker.first_name, job_seeker.last_name]:
        assert pii.upper() not in payload.upper()


@pytest.mark.usefixtures("failing_urlconf")
def test_user_kind_and_organization_are_reported_as_tags(client, captured_event):
    """They say who ran into the error without naming anyone, as the logs already do."""
    membership = CompanyMembershipFactory()
    client.force_login(membership.user)

    client.get("/boom")

    event = captured_event()
    assert event["user"] == {"id": str(membership.user.pk)}
    assert event["tags"]["user_kind"] == UserKind.PROFESSIONAL
    assert event["tags"]["organization_type"] == "companies.Company"
    assert event["tags"]["organization_id"] == str(membership.company_id)


@pytest.mark.usefixtures("failing_urlconf")
def test_anonymous_user_is_reported_as_anonymous(client, captured_event):
    client.get("/boom")

    assert captured_event()["user"] == {"id": ANONYMOUS_USER_ID}


def test_error_raised_before_authentication_reports_a_user(client, mocker, captured_event):
    """The health check answers before `AuthenticationMiddleware` runs, and reports its own errors."""
    mocker.patch("itou.www.middleware.default_storage").exists.side_effect = OSError("S3 is down")

    response = client.get("/check-health")

    assert response.status_code == 500
    assert captured_event()["user"] == {"id": ANONYMOUS_USER_ID}


@pytest.mark.usefixtures("failing_urlconf")
def test_token_authenticated_request_is_reported_as_an_api_service_account(captured_event):
    """The API authenticates inside the view: the user is only known once the event is built."""
    token = ServiceToken.objects.create(service=Service.DATA_INCLUSION)
    api_client = APIClient(headers={"Authorization": f"Token {token.key}"}, raise_request_exception=False)

    api_client.get("/boom-api")

    assert captured_event()["user"] == {"id": "api_service_account"}
