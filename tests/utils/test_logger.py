import pytest
from django.conf import settings


@pytest.mark.parametrize(
    "logger,match",
    [
        ("django_datadog_logger.middleware", None),
        ("django_datadog_logger.middleware.request_log", "django_datadog_logger.middleware.request_log"),
        ("django_datadog_logger.middleware.request_log.foo", None),
        ("itou", "itou"),
        ("itou.", None),
        ("itou.eligibility", "itou.eligibility"),
        ("itou.eligibility.tasks", "itou.eligibility.tasks"),
    ],
)
def test_extra_kwargs_in_logger(logger, match):
    if match:
        assert settings.DJANGO_DATADOG_LOGGER_EXTRA_INCLUDE.match(logger).string == match
    else:
        assert settings.DJANGO_DATADOG_LOGGER_EXTRA_INCLUDE.match(logger) is None
