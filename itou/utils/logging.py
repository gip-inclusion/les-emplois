import logging

from django_datadog_logger.formatters import datadog


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
        return log_entry_dict
