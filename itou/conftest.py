import pytest
from django.conf import settings
from django.contrib.gis.db.models.fields import get_srid_info
from django.core import management
from django.core.cache import cache
from django.db import connection

from itou.utils.htmx.testing import HtmxClient
from itou.utils.test import NoInlineClient


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Automatically add pytest db marker if needed."""
    for item in items:
        markers = {marker.name for marker in item.iter_markers()}
        if "no_django_db" not in markers and "django_db" not in markers:
            item.add_marker(pytest.mark.django_db)


@pytest.fixture
def client():
    return NoInlineClient()


@pytest.fixture()
def htmx_client():
    """
    Mimic a response to an HTMX request.

    Usage
    ```
    def my_test(htmx_client):
        response = htmx_client.get("/)
    ```
    """
    return HtmxClient()


@pytest.fixture(autouse=True, scope="session")
def preload_spatial_reference(django_db_setup, django_db_blocker):
    """
    Any first acces to a PostGIS field with geodjango loads the associated spatial
    reference information in an memory cache within Django.
    This fixture ensures this cache has been filled so that we have a consistent amount
    of database requests between tests to avoid a potential source of flakiness.

    Make a request for every spatial reference in use in the project.
    """
    with django_db_blocker.unblock():
        get_srid_info(4326, connection)


@pytest.fixture(autouse=True, scope="session", name="django_loaddata")
def django_loaddata_fixture(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        management.call_command(
            "loaddata",
            *{
                "test_asp_INSEE_communes_factory.json",
                "test_asp_INSEE_countries_factory.json",
            },
        )


@pytest.fixture(autouse=True)
def reset_cache():
    cache.clear()


@pytest.fixture(autouse=True, scope="session")
def django_test_environment_email_fixup(django_test_environment) -> None:
    # Django forcefully sets the EMAIL_BACKEND to
    # "django.core.mail.backends.locmem.EmailBackend" in
    # django.test.utils.setup_test_environment.
    settings.EMAIL_BACKEND = "itou.utils.tasks.AsyncEmailBackend"
    settings.ASYNC_EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
