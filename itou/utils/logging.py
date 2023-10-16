from django_datadog_logger.formatters import datadog


class ItouDataDogJSONFormatter(datadog.DataDogJSONFormatter):
    # We don't want those information in our logs
    LOG_KEYS_TO_REMOVE = ["usr.name", "usr.email"]

    def json_record(self, message, extra, record):
        log_entry_dict = super().json_record(message, extra, record)
        for log_key in self.LOG_KEYS_TO_REMOVE:
            if log_key in log_entry_dict:
                del log_entry_dict[log_key]
        return log_entry_dict
