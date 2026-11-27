import logging

from django_datadog_logger.formatters.datadog import get_wsgi_request_user
from itoutils.django.logging import DataDogJSONFormatter

from itou.utils.redaction import redact_personal_data


logger = logging.getLogger(__name__)


NO_RECURSIVE_LOG_FLAG = "_no_recursive_log_flag"


def current_organization_info(request):
    """Describe the organization the user acts for by its type and its ID, which name no one.

    Shared by the logs and the Sentry events, so that both report the same facts.
    """
    if organization := getattr(request, "current_organization", None):
        return {"organization_type": organization._meta.label, "organization_id": organization.pk}
    return {}


class ItouDataDogJSONFormatter(DataDogJSONFormatter):
    # The entries most likely to quote an outgoing URL or an email address. Not exhaustive, but much
    # cheaper than redacting every nested string of the entry
    # See also django_datadog_logger/formatters/datadog.py
    REDACTED_LOG_KEYS = ["message", "error.message", "error.stack"]

    def __init__(self, *args, redact=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.redact = redact

    def json_record(self, message, extra, record):
        log_entry_dict = super().json_record(message, extra, record)
        wsgi_request = self.get_wsgi_request()
        if wsgi_request is not None:
            for key, value in current_organization_info(wsgi_request).items():
                log_entry_dict[f"usr.{key}"] = value
            user = get_wsgi_request_user(wsgi_request)
            if token := getattr(wsgi_request, "auth", None):
                if hasattr(token, "datadog_info"):
                    log_entry_dict["token"] = token.datadog_info()
                else:
                    try:
                        user_pk = user.pk
                    except AttributeError:
                        user_pk = None
                    if user_pk is None and not getattr(wsgi_request, NO_RECURSIVE_LOG_FLAG, False):
                        # Avoid coming right back here with the following logger.warning
                        setattr(wsgi_request, NO_RECURSIVE_LOG_FLAG, True)
                        logger.warning(
                            "Request using token (%r) without datadog_info() method: please define one", token
                        )
            elif user is not None:
                log_entry_dict["usr.kind"] = user.kind
            if session := getattr(wsgi_request, "session", None):
                if hijack_history := session.get("hijack_history", []):
                    log_entry_dict["usr.hijack_history"] = hijack_history
        if self.redact:
            self._redact_entry(log_entry_dict)
        return log_entry_dict

    def _redact_entry(self, log_entry_dict):
        """Redact the email addresses and the query strings of the outgoing URLs of a log entry.

        Done on the output rather than on the record, which a filter would have to rewrite for
        every handler: the logging integration of Sentry reads the same record afterwards, and
        groups its events by message template. It also reaches the traceback, which the record
        only holds as an exception, and a message that is not a string, such as `logger.error(exc)`.
        """
        for key in self.REDACTED_LOG_KEYS:
            if isinstance(value := log_entry_dict.get(key), str):
                log_entry_dict[key] = redact_personal_data(value)
