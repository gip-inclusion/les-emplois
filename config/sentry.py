import functools
import logging
import os
import re
import traceback

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.huey import HueyIntegration
from sentry_sdk.integrations.logging import LoggingIntegration, ignore_logger_for_events
from sentry_sdk.integrations.redis import RedisIntegration

from itou.utils.redaction import (
    ANONYMOUS_USER_ID,
    REDACTED,
    can_hold_personal_data,
    redact_keyed_values,
    redact_personal_data,
    redact_query_values,
    redact_query_values_by_default,
)


logger = logging.getLogger(__name__)

# A key holding one of these is sensitive whatever is spelled around it: `birth_place`,
# `adresseEmail`, `numeroTelephone`, `address_line_1`, `contact_phone`, `referent_first_name`…
# `nom` and `name` are deliberately absent: they sit inside `denomination`, `nombre`,
# `template_name` or `model_name`, and those are the variables that make a traceback readable.
# The identity spellings are enumerated in the lists below, or caught by `first_name`,
# `last_name`, `full_name` and `_nom`, which ends the French field names (`candidat_nom`).
SENSITIVE_KEY_FRAGMENTS = {
    "_nom",
    "address",
    "adresse",
    "birth",
    "email",
    "first_name",
    "france_travail_id",
    "full_name",
    "hexa_",  # the components of an address in the format of the ASP, see itou.users.models.JobSeekerProfile
    "last_name",
    "naissance",
    "nir",
    "phone",
    "pole_emploi_id",
    "prenom",
    "telephone",
}

# The credential terms the SDK matches on its own in the headers it collects (see
# `sentry_sdk.data_collection`), applied here to the frame variables and the mappings it never
# visits. Those that would redact too much as fragments are not: `key` and `sid` are the whole
# names below, as is `auth` (inside `author`).
# `sso` (inside `processor`) and `identity` (inside `identity_provider`) are left out.
SENSITIVE_CREDENTIAL_FRAGMENTS = {
    "apikey",
    "api_key",
    "authorization",
    "bearer",
    "credentials",
    "csrf",
    "jwt",
    "passwd",
    "password",
    "pwd",
    "secret",
    "session",
    "token",
    "xsrf",
}

# Whole names, for what no fragment above can catch without redacting far more than intended:
# as fragments, `ft_id` would redact `draft_id` and `ip` would redact `description`
SENSITIVE_VARIABLE_NAMES = {
    "ft_id",
    "ip",  # see itou.audit_trail.models.AuditTrail
    # The other names of an IP address that the `EventScrubber` of sentry-sdk 2.x matched
    "remote_addr",
    "x_forwarded_for",
    "x_real_ip",
}

# Credential terms the SDK matches as fragments in the headers it collects, matched here as whole
# keys: as fragments they would redact `author`, `cache_key` and `residence`. A bare `key` is also
# what the OTP views name the TOTP secret, see itou.www.otp_views.views. The others are the keys
# that the `EventScrubber` of sentry-sdk 2.x matched and that no fragment above catches, save the
# session cookies of other frameworks (`PHPSESSID`, `connect.sid`, `symfony`).
SENSITIVE_CREDENTIAL_NAMES = {
    "auth",
    "cookie",
    "key",
    "private_key",
    "privatekey",
    "set_cookie",
    "sid",
}

# An inventory of the personal data the partner APIs send and return. The fragments
# above already catch most of them and are what covers the next spelling: these lists
# document the APIs, and give the tests the parameter names to look for in an event.
SENSITIVE_API_RESPONSE_FIELDS = {
    # France Travail, see itou.utils.apis.france_travail_agent.fetch_and_parse_user_data
    "adresseEmail",
    "codeInseeCommune",
    "codePostal",
    "complementAdresse",
    "complementDestinataire",
    "complementDistribution",
    "indicateurResidentQPV",
    "libelleCommune",
    "nom",
    "nomCorrespondance",
    "numeroTelephone",
    "numeroTypeLibelleVoie",
    "prenomCorrespondance",
    # ProConnect, see itou.openid_connect.pro_connect
    "family_name",
    "given_name",
    "usual_name",
}

SENSITIVE_API_PARAMETERS = {
    # API Particulier, see itou.utils.apis.api_particulier
    "anneeDateNaissance",
    "codeCogInseeCommuneNaissance",
    "codeCogInseePaysNaissance",
    "jourDateNaissance",
    "moisDateNaissance",
    "nomNaissance",  # also sent to France Travail by recherche_individu_certifie
    "prenoms[]",  # prenoms%5B%5D in the URL
    "sexeEtatCivil",
    # France Travail, see itou.utils.apis.pole_emploi
    "dateNaissance",
    "nirCertifie",
    "numeroFranceTravail",
    "prenom",
    # Employee records sent to the ASP, see itou.employee_record.serializers
    "nomUsage",
}

NON_SENSITIVE_KEYS = {
    "active_members_email_reminder_last_sent_at",  # when an organization was last reminded of its members
    "address_filled_at",  # when a user filled in their address, see itou.users.models.User
    "approval_number_sent_by_email",  # a boolean of itou.job_applications.models.JobApplication
    # The habilitation of a prescriber organization, see itou.prescribers.models.PrescriberOrganization
    "authorization_status",
    "authorization_updated_at",
    "authorization_updated_by",
    "authorization_updated_by_id",
    # The primary key of an allauth `EmailAddress`, whereas the `email_address` it points at is an address
    "email_address_id",
    "email_id",  # the primary key of an itou.emails.models.Email row, logged when sending fails
    # Whether a user accepts the tracking of the emails sent to them, and when they last said so
    "email_tracking_consent",
    "email_tracking_consent_updated_at",
    "had_nir",  # a boolean kept on anonymized job seekers
    "had_pole_emploi_id",  # a boolean kept on anonymized job seekers
    "lack_of_nir_reason",  # why a job seeker has no NIR, not a NIR
    "lack_of_pole_emploi_id_reason",  # why a job seeker has no France Travail ID, not an ID
    "last_reminder_email_sent_at",  # when an orientation was last reminded, see itou.insertion.models
    "pe_obfuscated_nir",  # the France Travail "id national", obfuscated by design
    "pole_emploi_id_forgotten",  # a boolean of the job seeker forms
    "require_phone_interview",  # a boolean of the PASS IAE forms
    "sender_prescriber_organization_authorization_status",  # kept on anonymized job applications
    "training_session",  # what a sanctioned company has to attend, see itou.siae_evaluations.models.Sanctions
}

_SENSITIVE_NAMES = (
    SENSITIVE_API_PARAMETERS | SENSITIVE_API_RESPONSE_FIELDS | SENSITIVE_VARIABLE_NAMES | SENSITIVE_CREDENTIAL_NAMES
)
_SENSITIVE_NAMES_LOWER = frozenset(name.lower() for name in _SENSITIVE_NAMES)
_SENSITIVE_FRAGMENTS_RE = re.compile(
    "|".join(re.escape(fragment) for fragment in sorted(SENSITIVE_KEY_FRAGMENTS | SENSITIVE_CREDENTIAL_FRAGMENTS))
)
# The keys holding a bare query string: `http.query` in the HTTP breadcrumbs and the span of our
# own request, `url.query` in the spans of an outgoing request since sentry-sdk 3.0
_QUERY_STRING_KEYS = frozenset({"http.query", "url.query"})

# The only form fields whose value is sent to Sentry, all others being redacted by
# `scrub_request_data`. Keep it short: forms of this app mostly collect personal data, so only
# add a field whose value can never describe a person (IDs, pagination, routing, SIRET).
READABLE_FORM_FIELDS = re.compile(
    r"""^(
        (.+_)?u?ids?  # the objects the submission points at
        | (.+_)?pks?
        | page
        | next(_url)?
        | action | kind | role | status | type
        | siret
        | form-(TOTAL|INITIAL|MIN_NUM|MAX_NUM)_FORMS  # what a formset says about its own size
    )$""",
    re.VERBOSE | re.IGNORECASE,
)

PII_SCRUBBING_FAILED = "PII scrubbing failed"
# Where the scrubbing code lives, and so the frame that says why it failed
_SCRUBBING_FILES = ("config/sentry.py", "itou/utils/redaction.py")

# Span attributes that never carry personal data: the only ones kept when scrubbing fails
SPAN_PII_FREE_ATTRIBUTES = [
    "http.request.method",
    "http.response.status_code",
    "sentry.environment",
    "sentry.op",
    "sentry.origin",
    "sentry.release",
    "sentry.sdk.name",
    "sentry.sdk.version",
    "sentry.segment.id",
    "sentry.segment.name",
]

# Event fields that never carry personal data: the only ones kept when scrubbing fails
EVENT_PII_FREE_KEYS = [
    "dist",
    "environment",
    "event_id",
    "level",
    "logger",
    "platform",
    "release",
    "sdk",
    "server_name",
    "timestamp",
    "transaction",
    "type",
]


# The keys repeat heavily, from one span or one frame to the next
@functools.lru_cache(maxsize=4096)
def _is_sensitive_key(key):
    """Whether a mapping key, a variable name or a query parameter names something private.

    The single predicate behind every layer below, so that the mappings of an event, its frame
    variables and the query strings found in its free text cannot end up protecting three
    different sets of keys.
    """
    if not isinstance(key, str):
        return False
    key = key.lower()
    if key in NON_SENSITIVE_KEYS:
        return False
    return key in _SENSITIVE_NAMES_LOWER or bool(_SENSITIVE_FRAGMENTS_RE.search(key))


def _scrub_dict_value(key, value):
    if _is_sensitive_key(key):
        return REDACTED
    if key in _QUERY_STRING_KEYS and isinstance(value, str):
        # A query string without a host, so we can't tell whether it comes from an outgoing API
        # call or from a request to our own site. We therefore redact every value, except
        # `NON_PERSONAL_QUERY_KEYS`
        return redact_query_values_by_default(value)
    return scrub_sensitive_data(value)


def scrub_sensitive_data(value):
    """Redact personal data anywhere in a Sentry event.

    This includes: the message of an exception, the log entry, breadcrumbs, span data, and
    the local variables of the stack frames.

    It is the only layer to do so: sentry-sdk 3.0 removed the SDK's `EventScrubber`, so this
    has to reach every depth of every mapping on its own.
    """
    match value:
        case str():
            if not can_hold_personal_data(value):
                return value
            value = redact_personal_data(value)
            # Catches the query strings that `redact_personal_data` misses because no `https://host`
            # precedes them, such as our own request's `query_string` or a relative
            # `next=/path?nir=...`.
            value = redact_query_values(value, _is_sensitive_key)
            return redact_keyed_values(value, _is_sensitive_key)
        case dict():
            return {key: _scrub_dict_value(key, item) for key, item in value.items()}
        case list():
            return [scrub_sensitive_data(item) for item in value]
        case tuple():
            return tuple(scrub_sensitive_data(item) for item in value)
    return value


def scrubbed_repr(value):
    """`custom_repr` hook to scrub a container before the SDK turns it into a string.

    The SDK serializes a mapping nested deeper than `MAX_DATABAG_DEPTH` (5) as its repr, which
    `scrub_sensitive_data` could only read as text. Scrubbing it first keeps a sensitive key
    redacted whatever its value holds. Anything else gets the SDK's own repr.
    """
    if isinstance(value, (dict, list, tuple)):
        return repr(scrub_sensitive_data(value))
    return None


def scrub_request_data(event):
    """Redact the values of a submitted form, keeping its field names.

    Which fields were submitted, and which were left blank, is what makes a failed submission
    debuggable: their values describe a person far more often than not. So this one channel is
    the reverse of the denylist used everywhere else, which is only tenable because the field
    names are ours. Nothing in `data_collection` gates the body by key: it arrives whole.
    """
    request = event.get("request")
    if not isinstance(request, dict) or "data" not in request:
        return
    data = request["data"]
    if isinstance(data, dict):
        request["data"] = {key: value if _is_readable_form_field(key) else REDACTED for key, value in data.items()}
    elif data:  # A raw body the SDK could not parse, so there is no field name to decide on
        request["data"] = REDACTED


def _is_readable_form_field(key):
    return isinstance(key, str) and bool(READABLE_FORM_FIELDS.match(key)) and not _is_sensitive_key(key)


def anonymize_user(event):
    """Reduce the user of an event to its ID.

    `itou.www.middleware.sentry_user_id` only ever sets the ID. This is the safety net, should
    the SDK or another integration attach more: keeping the ID rather than dropping known keys
    also drops `name`, `geo`, `segment` or whatever comes next.
    """
    if "user" in event:
        event["user"] = {"id": event["user"].get("id", ANONYMOUS_USER_ID)}


def _failed_scrubbing_event():
    """The part of the event sent when scrubbing failed that does not depend on the event."""
    return {"message": PII_SCRUBBING_FAILED, "tags": {"pii_scrubbing": "failed"}}


def _scrubbing_failure(exc):
    """Describe why scrubbing failed by the type of the exception and the line raising it.

    That is what fixing the scrubber takes, whereas the message of the exception can quote the
    very value being scrubbed, so it is never reported.
    """
    frames = [frame for frame in traceback.extract_tb(exc.__traceback__) if frame.filename.endswith(_SCRUBBING_FILES)]
    location = f"{os.path.basename(frames[-1].filename)}:{frames[-1].lineno}" if frames else "unknown"
    return {"pii_scrubbing_error": type(exc).__qualname__, "pii_scrubbing_location": location}


def degraded_event(event, exc):
    """Reduce an event to the fields that cannot carry personal data, once scrubbing failed.

    Rather than silencing the error or letting personal data through, keep the alert firing.
    The message is hardcoded to give the issue a stable, greppable title instead of
    “<unlabeled event>”. The exception types are the one detail of the event known to be safe,
    and they also group the degraded events, so that muting one of their issues does not hide
    every later failure. Everything else goes, `contexts` included, and with it the trace that
    would link this event to its spans.
    """
    degraded = _failed_scrubbing_event()
    degraded.update({key: event[key] for key in EVENT_PII_FREE_KEYS if key in event})
    exception_types = [
        value["type"]
        for value in event.get("exception", {}).get("values", [])
        if isinstance(value, dict) and "type" in value
    ]
    if exception_types:
        degraded["tags"]["exception_type"] = ",".join(exception_types)
    degraded["tags"].update(_scrubbing_failure(exc))
    degraded["fingerprint"] = ["pii-scrubbing-failed", *exception_types]
    return degraded


def scrub_event(event):
    """Remove personal data from an error event."""
    anonymize_user(event)
    scrub_request_data(event)
    return scrub_sensitive_data(event)


def strip_sentry_sensitive_data(event, _hint):
    """`before_send` hook to remove personal data from Sentry events.

    Breadcrumbs only leave the process inside an error event, so this is also what scrubs them:
    no `before_breadcrumb` hook is needed.

    When scrubbing raises, the event is not sent as it is but reduced by `degraded_event`: a bug
    in the scrubber costs the details of the event, not the alert. Also, you cannot use the
    debugger here.
    """
    try:
        return scrub_event(event)
    except Exception as exc:
        try:
            return degraded_event(event, exc)
        except Exception:
            # The fallback itself must not raise: the SDK would drop the event, leaving nothing
            # but a `callback_error` in the client reports of the project.
            return {"event_id": event["event_id"], "level": "error", **_failed_scrubbing_event()}


def scrub_span(span):
    """Remove personal data from the name and the attributes of a span, all the SDK reads back."""
    attributes = {
        key: value
        for key, value in (span.get("attributes") or {}).items()
        # The user is reduced to its ID, as on an error, see `anonymize_user`
        if not key.startswith("user.") or key == "user.id"
    }
    return {**span, "name": scrub_sensitive_data(span["name"]), "attributes": scrub_sensitive_data(attributes)}


def degraded_span(span, failure):
    """Reduce a span to the attributes that cannot carry personal data, once scrubbing failed.

    Its place in the trace and its duration are kept: the SDK only lets `before_send_span`
    change the name and the attributes of a span.
    """
    attributes = span.get("attributes") or {}
    return {
        "name": PII_SCRUBBING_FAILED,
        "attributes": {
            **{key: attributes[key] for key in SPAN_PII_FREE_ATTRIBUTES if key in attributes},
            "pii_scrubbing": "failed",
            **failure,
        },
    }


def strip_sentry_sensitive_data_from_span(span, _hint):
    """`before_send_span` hook to remove personal data from Sentry spans.

    Spans carry the URL of outgoing HTTP requests, and the URL and the headers of our own.

    Since sentry-sdk 3.0, spans are streamed one by one and cannot be dropped, and the SDK sends
    a span as it was when this hook raises. So when scrubbing fails, the span is reduced by
    `degraded_span`, and why it failed is logged, which Sentry ignores.
    """
    try:
        return scrub_span(span)
    except Exception as exc:
        try:
            failure = _scrubbing_failure(exc)
            logger.warning(
                "Degraded a span, scrubbing it raised %(pii_scrubbing_error)s at %(pii_scrubbing_location)s", failure
            )
            return degraded_span(span, failure)
        except Exception:
            # Raising would send the span as it was
            return {"name": PII_SCRUBBING_FAILED, "attributes": {"pii_scrubbing": "failed"}}


def sentry_init():
    try:
        traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", ""))
    except ValueError:
        traces_sample_rate = 0

    try:
        shutdown_timeout_option = {"shutdown_timeout": int(os.getenv("SENTRY_SHUTDOWN_TIMEOUT", ""))}
    except ValueError:
        shutdown_timeout_option = {}

    sentry_sdk.init(
        # DSN is read from the SENTRY_DSN environment variable.
        integrations=[
            LoggingIntegration(
                # No Sentry logs: since sentry-sdk 3.0, `level` sends the records as Sentry logs,
                # which `before_send` never sees. The logs go to Datadog, redacted.
                level=None,
                breadcrumb_level=logging.INFO,  # Capture info and above as breadcrumbs.
                event_level=logging.ERROR,  # Send errors as events.
            ),
            DjangoIntegration(middleware_spans=True, signals_spans=True, cache_spans=True, db_transaction_spans=True),
            HttpxIntegration(),
            HueyIntegration(),
            # Hardcoded CACHES.*.KEY_PREFIX to not depend on Django being setup
            RedisIntegration(cache_prefixes=["django:"]),
        ],
        # https://docs.sentry.io/platforms/python/sampling/
        traces_sample_rate=traces_sample_rate,
        # Since sentry-sdk 3.0, the stack, local variables included, is attached to every message
        # and every error log by default. They say where they come from already, and each frame
        # would be as many more values for `before_send` to scrub.
        attach_stacktrace=False,
        # What the integrations are allowed to collect, category by category. It replaces
        # `send_default_pii`, which sentry-sdk 3.0 removed, and whose defaults collected less.
        # https://docs.sentry.io/platforms/python/configuration/options/#data_collection
        # https://docs.sentry.io/platforms/python/data-management/data-collected/
        # https://develop.sentry.dev/sdk/foundations/client/data-collection/
        data_collection={  # introduced with sentry-sdk 2.70.0
            # `itou.www.middleware.sentry_user_id` attaches the user ID, and nothing else
            "user_info": False,
            "cookies": {"mode": "off"},
            # The terms `send_default_pii=False` used to imply. Without them, the forwarding
            # headers, which carry the IP address of the visitor, would come back.
            "http_headers": {
                "request": {"mode": "denylist", "terms": ["forwarded", "-ip", "remote-", "via", "-user"]}
            },
            # The submitted form, which `scrub_request_data` reduces to its field names
            "http_bodies": ["incoming_request"],
            # Filtered by the SDK before `before_send` and `before_send_span` run, for incoming and outgoing requests.
            # The SDK always masks its own credential terms (`key`, `auth`, `token`...), ours add up.
            # "off" would drop everything, even `?page=2`, which makes errors harder to reproduce.
            "url_query_params": {"mode": "denylist", "terms": sorted(SENSITIVE_KEY_FRAGMENTS)},
            "graphql": {"document": False, "variables": False},
            "gen_ai": {"inputs": False, "outputs": False},
            "mcp": {"inputs": False, "outputs": False},
            "database_query_data": False,
            # The frames are what makes an error diagnosable, `before_send` scrubs them. The
            # `{"mode": "denylist"}` of the SDK would only test the names of the locals, not the
            # keys of the mappings they hold, with terms such as `key` or `auth` that would also
            # hide `cache_key` or `author`.
            "stack_frame_variables": True,
            "frame_context_lines": 5,
            # The arguments of a Huey task say which record failed, and are scrubbed like
            # any other mapping. Personal ones are passed by keyword so that they are keyed,
            # see `itou.archive.tasks` and `itou.external_data.tasks`.
            "queues": True,
        },
        # https://docs.sentry.io/platforms/python/data-management/sensitive-data/#before-send-before-send-transaction--before-send-span
        # https://docs.sentry.io/platforms/python/configuration/filtering/
        before_send=strip_sentry_sensitive_data,
        before_send_span=strip_sentry_sensitive_data_from_span,
        # https://docs.sentry.io/platforms/python/configuration/options/#custom_repr
        custom_repr=scrubbed_repr,
        **shutdown_timeout_option,
    )
    ignore_logger_for_events("django.security.DisallowedHost")
    ignore_logger_for_events("django_datadog_logger.middleware.request_log")
    # Its warnings are about the scrubbing itself, which they would only go through again
    ignore_logger_for_events(__name__)
