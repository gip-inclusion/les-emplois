import logging

import httpx
from django.conf import settings
from django_datadog_logger.formatters import datadog

from itou.utils.command import get_current_command_info


logger = logging.getLogger(__name__)


NO_RECURSIVE_LOG_FLAG = "_no_recursive_log_flag"


class ItouDataDogJSONFormatter(datadog.DataDogJSONFormatter):
    # We don't want those information in our logs
    LOG_KEYS_TO_REMOVE = ["usr.name", "usr.email", "usr.session_key"]

    def json_record(self, message, extra, record):
        log_entry_dict = super().json_record(message, extra, record)
        for log_key in self.LOG_KEYS_TO_REMOVE:
            if log_key in log_entry_dict:
                del log_entry_dict[log_key]
        wsgi_request = self.get_wsgi_request()
        if wsgi_request is not None:
            if current_org := getattr(wsgi_request, "current_organization", None):
                log_entry_dict["usr.organization_id"] = current_org.pk
            if token := getattr(wsgi_request, "auth", None):
                if hasattr(token, "datadog_info"):
                    log_entry_dict["token"] = token.datadog_info()
                else:
                    try:
                        user_pk = wsgi_request.user.pk
                    except AttributeError:
                        user_pk = None
                    if user_pk is None and not getattr(wsgi_request, NO_RECURSIVE_LOG_FLAG, False):
                        # Avoid coming right back here with the following logger.warning
                        setattr(wsgi_request, NO_RECURSIVE_LOG_FLAG, True)
                        logger.warning(
                            "Request using token (%r) without datadog_info() method: please define one", token
                        )
            if session := getattr(wsgi_request, "session", None):
                if hijack_history := session.get("hijack_history", []):
                    log_entry_dict["usr.hijack_history"] = hijack_history
        if (command_info := get_current_command_info()) is not None:
            log_entry_dict["command.run_uid"] = command_info.run_uid
            log_entry_dict["command.name"] = command_info.name
            log_entry_dict["command.wet_run"] = command_info.wet_run
        return log_entry_dict


class HTTPXFilter(logging.Filter):
    def filter(self, record):
        new_args = []
        for arg in record.args:
            # We could add more sensitive urls to redact: add them here
            # In the future, we might want to parametrize this filter but YAGNI

            if isinstance(arg, httpx.URL):
                if str(arg).startswith(settings.API_PARTICULIER_BASE_URL):
                    redacted_params = [(key, "_REDACTED_") for key, _value in arg.params.multi_items()]
                    arg = arg.copy_with(params=redacted_params)
                elif str(arg).startswith(f"{settings.BREVO_API_URL}/contacts/"):
                    identifier = arg.path.removeprefix("/v3/contacts/")
                    if "@" in identifier:
                        # This is an email address, redact it
                        arg = arg.copy_with(path="/v3/contacts/_REDACTED_")
            new_args.append(arg)
        record.args = tuple(new_args)
        return super().filter(record)
