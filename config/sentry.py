import logging
import os

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.huey import HueyIntegration
from sentry_sdk.integrations.logging import LoggingIntegration, ignore_logger
from sentry_sdk.integrations.redis import RedisIntegration

from itou.utils.redaction import (
    REDACTED,
    redact_personal_data,
    redact_query_values,
    redact_query_values_by_default,
)


# A key holding one of these is sensitive whatever is spelled around it: `birth_place`,
# `adresseEmail`, `numeroTelephone`, `address_line_1`, `contact_phone`, `date_naissance`…
# `nom` and `name` are deliberately absent: they sit inside `denomination`, `nombre`,
# `template_name` or `model_name`, and those are the variables that make a traceback readable.
SENSITIVE_KEY_FRAGMENTS = {
    "address",
    "adresse",
    "birth",
    "email",
    "france_travail_id",
    "naissance",
    "nir",
    "phone",
    "pole_emploi_id",
    "prenom",
    "telephone",
}

# Whole names, for what no fragment above can catch without redacting far more than intended
SENSITIVE_VARIABLE_NAMES = {
    "first_name",
    "ft_id",
    "last_name",
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
    "email_id",  # the primary key of an itou.emails.models.Email row, logged when sending fails
    "had_nir",  # a boolean kept on anonymized job seekers
    "had_pole_emploi_id",  # a boolean kept on anonymized job seekers
    "lack_of_nir_reason",  # why a job seeker has no NIR, not a NIR
    "lack_of_pole_emploi_id_reason",  # why a job seeker has no France Travail ID, not an ID
    "pe_obfuscated_nir",  # the France Travail "id national", obfuscated by design
    "pole_emploi_id_forgotten",  # a boolean of the job seeker forms
    "require_phone_interview",  # a boolean of the PASS IAE forms
}

_SENSITIVE_NAMES = SENSITIVE_API_PARAMETERS | SENSITIVE_API_RESPONSE_FIELDS | SENSITIVE_VARIABLE_NAMES
_SENSITIVE_NAMES_LOWER = frozenset(name.lower() for name in _SENSITIVE_NAMES)


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
    return key in _SENSITIVE_NAMES_LOWER or any(fragment in key for fragment in SENSITIVE_KEY_FRAGMENTS)


def _scrub_dict_value(key, value):
    if _is_sensitive_key(key):
        return REDACTED
    if key == "http.query" and isinstance(value, str):
        # `http.query` holds a query string without a host, so we can't tell whether it comes from
        # an outgoing API call or from a request to our own site. We therefore redact every
        # value, except `NON_PERSONAL_QUERY_KEYS`
        return redact_query_values_by_default(value)
    return scrub_sensitive_data(value)


def scrub_sensitive_data(value):
    """Redact personal data anywhere in a Sentry event.

    This includes: the message of an exception, the log entry, breadcrumbs, and
    the local variables of the stack frames.
    """
    match value:
        case str():
            value = redact_personal_data(value)
            # Catches the query strings that `redact_personal_data` misses because no `https://host`
            # precedes them, such as our own request's `query_string` or a relative
            # `next=/path?nir=...`.
            return redact_query_values(value, _is_sensitive_key)
        case dict():
            return {key: _scrub_dict_value(key, item) for key, item in value.items()}
        case list():
            return [scrub_sensitive_data(item) for item in value]
        case tuple():
            return tuple(scrub_sensitive_data(item) for item in value)
    return value


def anonymize_user(event):
    """Keep the user ID, drop everything else identifying them."""
    if "user" in event:
        # Unfortunately this does not work for the IP address
        # which keeps appearing. ¯\_(ツ)_/¯
        keys_to_delete_if_present = ["email", "username", "ip_address"]
        for key in keys_to_delete_if_present:
            if key in event["user"]:
                del event["user"][key]
        # Identify clearly users who have not logged in.
        if "id" not in event["user"]:
            event["user"]["id"] = "anonymous"


def strip_sentry_sensitive_data(event, _hint):
    """`before_send` hook to remove personal data from Sentry events.

    Breadcrumbs only leave the process inside an error event, so this is also what scrubs them:
    no `before_breadcrumb` hook is needed.

    Be very cautious about not raising any exception in this method. Indeed, when it happens,
    the initial 500 error never reaches the sentry servers and it could take months before we
    realize a real error was silenced. Also, you cannot use the debugger here.
    """
    anonymize_user(event)
    return scrub_sensitive_data(event)


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
                level=logging.INFO,  # Capture info and above as breadcrumbs.
                event_level=logging.ERROR,  # Send errors as events.
            ),
            DjangoIntegration(middleware_spans=True, signals_spans=True, cache_spans=True, db_transaction_spans=True),
            HttpxIntegration(),
            HueyIntegration(),
            # Hardcoded CACHES.*.KEY_PREFIX to not depend on Django being setup
            RedisIntegration(cache_prefixes=["django:"]),
        ],
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        traces_sample_rate=traces_sample_rate,
        # Associate users (ID+email+username+IP) to errors.
        # https://docs.sentry.io/platforms/python/django/
        send_default_pii=True,
        # https://docs.sentry.io/platforms/python/data-management/sensitive-data/#before-send-before-send-transaction--before-send-span
        # https://docs.sentry.io/platforms/python/configuration/filtering/
        before_send=strip_sentry_sensitive_data,
        # The alternative solution
        # https://docs.sentry.io/enriching-error-data/additional-data/?platform=python#capturing-the-user
        # only ever works here (without access to `request.user`)
        # and is silently ignored when used in `context_processors.py` to get access to `request.user`.
        **shutdown_timeout_option,
    )
    ignore_logger("django.security.DisallowedHost")
    ignore_logger("django_datadog_logger.middleware.request_log")
