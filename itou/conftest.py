import os

# Workaround being able to use freezegun with pandas.
# https://github.com/spulec/freezegun/issues/98
import pandas  # noqa F401
import pytest
from django.conf import settings
from django.contrib.gis.db.models.fields import get_srid_info
from django.core import management
from django.core.cache import cache
from django.db import connection
from factory import Faker


# Rewrite before importing itou code.
pytest.register_assert_rewrite("itou.utils.test")

from itou.utils import faker_providers  # noqa: E402
from itou.utils.htmx.test import HtmxClient  # noqa: E402
from itou.utils.test import NoInlineClient  # noqa: E402


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


@pytest.fixture(autouse=True, scope="session")
def itou_faker_provider(_session_faker):
    _session_faker.add_provider(faker_providers.ItouProvider)  # For faker
    Faker.add_provider(faker_providers.ItouProvider)  # For factory_boy


@pytest.fixture(scope="function")
def unittest_compatibility(request, faker, snapshot):
    request.instance.faker = faker
    request.instance.snapshot = snapshot


@pytest.fixture(autouse=True)
def django_ensure_matomo_titles(monkeypatch) -> None:
    is_running_on_ci = os.getenv("CI", False)
    if not is_running_on_ci:
        return

    from django.template import base, defaulttags, loader, loader_tags

    original_render = loader.render_to_string

    def assertive_render(template_name, context=None, request=None, using=None):
        template = loader.get_template(template_name, using=using)

        def _walk_template_nodes(nodelist, condition_fn):
            for node in nodelist:
                if isinstance(node, (loader_tags.ExtendsNode, defaulttags.IfNode)):
                    return _walk_template_nodes(node.nodelist, condition_fn)
                if condition_fn(node):
                    return node

        def is_title_node(node):
            return isinstance(node, loader_tags.BlockNode) and node.name == "title"

        def is_variable_node(node):
            return (
                isinstance(node, base.VariableNode) and "block.super" not in str(node) and "CSP_NONCE" not in str(node)
            )

        title_node = _walk_template_nodes(template.template.nodelist, is_title_node)
        if title_node:
            var_node = _walk_template_nodes(title_node.nodelist, is_variable_node)
            if var_node and "matomo_custom_title" not in context:
                raise AssertionError(
                    f"template={template_name} uses a variable title; "
                    "please provide a `matomo_custom_title` in the context !"
                )
        return original_render(template_name, context, request, using)

    monkeypatch.setattr(loader, "render_to_string", assertive_render)
