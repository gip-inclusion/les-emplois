import os

# Workaround being able to use freezegun with pandas.
# https://github.com/spulec/freezegun/issues/98
import pandas  # noqa F401
import patchy
import pytest
from django.conf import settings
from django.contrib.gis.db.models.fields import get_srid_info
from django.core import management
from django.core.cache import cache
from django.db import connection
from django.template import base as base_template
from django.test import override_settings
from factory import Faker
from pytest_django.lazy_django import django_settings_is_configured
from pytest_django.plugin import INVALID_TEMPLATE_VARS_ENV


# Rewrite before importing itou code.
pytest.register_assert_rewrite("tests.utils.test", "tests.utils.htmx.test")

from itou.utils import faker_providers  # noqa: E402
from tests.users.factories import ItouStaffFactory  # noqa: E402
from tests.utils.htmx.test import HtmxClient  # noqa: E402
from tests.utils.test import NoInlineClient  # noqa: E402


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Automatically add pytest db marker if needed."""
    for item in items:
        markers = {marker.name for marker in item.iter_markers()}
        if "no_django_db" not in markers and "django_db" not in markers:
            item.add_marker(pytest.mark.django_db)


@pytest.fixture
def admin_client():
    client = NoInlineClient()
    client.force_login(ItouStaffFactory(is_superuser=True))
    return client


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


@pytest.fixture(autouse=True, scope="session")
def test_settings():
    with override_settings(S3_STORAGE_ENDPOINT_DOMAIN="localhost", S3_STORAGE_BUCKET_NAME="test"):
        yield


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
def unittest_compatibility(request, faker, snapshot, mocker):
    request.instance.faker = faker
    request.instance.snapshot = snapshot
    request.instance.mocker = mocker


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


@pytest.fixture(autouse=True, scope="session")
def _fail_for_invalid_template_variable_improved(_fail_for_invalid_template_variable):
    # Workaround following https://github.com/pytest-dev/pytest-django/issues/1059#issue-1665002785
    # rationale to better handle OneToOne field
    if os.environ.get(INVALID_TEMPLATE_VARS_ENV, "false") == "true" and django_settings_is_configured():
        from django.conf import settings as dj_settings

        invalid_var_exception = dj_settings.TEMPLATES[0]["OPTIONS"]["string_if_invalid"]

        # Make InvalidVarException falsy to keep the behavior consistent for OneToOneField
        invalid_var_exception.__class__.__bool__ = lambda self: False

        # but adapt Django's template code to behave as if it was truthy in resolve
        # (except when the default filter is used)
        patchy.patch(
            base_template.FilterExpression.resolve,
            """\
            @@ -7,7 +7,8 @@
                             obj = None
                         else:
                             string_if_invalid = context.template.engine.string_if_invalid
            -                if string_if_invalid:
            +                from django.template.defaultfilters import default as default_filter
            +                if default_filter not in {func for func, _args in self.filters}:
                                 if "%s" in string_if_invalid:
                                     return string_if_invalid % self.var
                                 else:
            """,
        )

        # By default, Django uses "" as string_if_invalid
        # when fail is set to False, try to mimic Django
        patchy.patch(
            invalid_var_exception.__class__.__mod__,
            """\
            @@ -7,4 +7,5 @@
                 if self.fail:
                     pytest.fail(msg)
                 else:
            -        return msg
            +        # If self.fail is desactivated, try to be discreet
            +        return ""
            """,
        )


@pytest.fixture(scope="session", autouse=True)
def make_unordered_queries_randomly_ordered():
    """
    Patch Django’s ORM to randomly order all queries without a specified
    order.

    This discovers problems where code expects a given order but the
    database doesn’t guarantee one.

    https://adamj.eu/tech/2023/07/04/django-test-random-order-querysets/
    """
    from django.db.models.sql.compiler import SQLCompiler

    patchy.patch(
        SQLCompiler._order_by_pairs,
        """\
        @@ -9,7 +9,7 @@
                 ordering = meta.ordering
                 self._meta_ordering = ordering
             else:
        -        ordering = []
        +        ordering = ["?"] if not self.query.distinct else []
             if self.query.standard_ordering:
                 default_order, _ = ORDER_DIR["ASC"]
             else:
        """,
    )
