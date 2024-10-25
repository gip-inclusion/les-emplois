import copy
import io
import os
import socket
import threading
import uuid

# Workaround being able to use freezegun with pandas.
# https://github.com/spulec/freezegun/issues/98
import pandas  # noqa F401
import paramiko
import patchy
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.contrib.gis.db.models.fields import get_srid_info
from django.core import management
from django.core.cache import cache
from django.core.files.storage import default_storage, storages
from django.core.management import call_command
from django.db import connection
from django.template import base as base_template
from django.test import override_settings
from factory import Faker
from paramiko import ServerInterface
from pytest_django.lazy_django import django_settings_is_configured
from pytest_django.plugin import INVALID_TEMPLATE_VARS_ENV


# Rewrite before importing itou code.
pytest.register_assert_rewrite("tests.utils.test", "tests.utils.htmx.test")

from itou.utils import faker_providers  # noqa: E402
from itou.utils.storage.s3 import s3_client  # noqa: E402
from tests.utils.htmx.test import HtmxClient  # noqa: E402
from tests.utils.test import ItouClient  # noqa: E402


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Automatically add pytest db marker if needed."""
    for item in items:
        markers = {marker.name for marker in item.iter_markers()}
        if "no_django_db" not in markers and "django_db" not in markers:
            item.add_marker(pytest.mark.django_db)


@pytest.hookimpl(trylast=True)
def pytest_configure(config) -> None:
    # Make sure pytest-randomly's pytest_collection_modifyitems hook runs before pytest-django's one
    # Note: _hookimpls execution order is reversed meaning that the last ones are run first
    config.pluginmanager.hook.pytest_collection_modifyitems._hookimpls.sort(
        key=lambda hook_impl: (
            hook_impl.wrapper or hook_impl.hookwrapper,  # Keep hookwrappers last
            hook_impl.plugin_name == "randomly",  # Then pytest-randomly's and after that all the other ones
        )
    )
    config.addinivalue_line(
        "markers",
        (
            "ignore_unknown_variable_template_error(*ignore_names): "
            "ignore unknown variable error in templates, optionally providing specific names to ignore"
        ),
    )


@pytest.fixture
def admin_client():
    from tests.users.factories import ItouStaffFactory

    client = ItouClient()
    client.force_login(ItouStaffFactory(is_superuser=True))
    return client


@pytest.fixture
def client():
    return ItouClient()


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


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
def preload_contenttype_cache(django_db_setup, django_db_blocker):
    from django.apps import apps
    from django.contrib.contenttypes.models import ContentType

    with django_db_blocker.unblock():
        ContentType.objects.get_for_models(*apps.get_models())


@pytest.fixture(autouse=True, scope="session")
def test_bucket():
    # TODO: Remove this code block once we stop using a models.URLField() to store a S3 link (ie. `resume_link`)
    from django.core.validators import URLValidator

    patchy.patch(
        URLValidator.__call__,
        '''\
        @@ -16,3 +16,5 @@ def __call__(self, value):
             try:
        +        if value.startswith("''' + settings.AWS_S3_ENDPOINT_URL + '''"):
        +           return
                 super().__call__(value)
             except ValidationError as e:
        ''',
    )  # fmt: skip

    call_command("configure_bucket", autoexpire=True)
    yield


@pytest.fixture(autouse=True)
def storage_prefix_per_test():
    public_storage = storages["public"]
    original_default_location = default_storage.location
    original_public_location = public_storage.location
    namespace = f"{uuid.uuid4()}"
    default_storage.location = namespace
    public_storage.location = namespace
    yield
    default_storage.location = original_default_location
    public_storage.location = original_public_location


@pytest.fixture(autouse=True)
def cache_per_test(settings):
    caches = copy.deepcopy(settings.CACHES)
    for cache_config in caches.values():
        cache_config["KEY_PREFIX"] = f"{uuid.uuid4()}"
    settings.CACHES = caches


@pytest.fixture(autouse=True)
def cached_announce_campaign():
    """
    Populates cache for AnnouncementCampaign to avoid an extra database hit in many tests
    """
    from itou.communications.cache import CACHE_ACTIVE_ANNOUNCEMENTS_KEY

    cache.set(CACHE_ACTIVE_ANNOUNCEMENTS_KEY, None, None)
    yield
    cache.delete(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)


@pytest.fixture
def empty_active_announcements_cache(cached_announce_campaign):
    from itou.communications.cache import CACHE_ACTIVE_ANNOUNCEMENTS_KEY

    cache.delete(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)
    yield


@pytest.fixture
def temporary_bucket():
    with override_settings(AWS_STORAGE_BUCKET_NAME=f"tests-{uuid.uuid4()}"):
        call_command("configure_bucket")
        yield
        client = s3_client()
        paginator = client.get_paginator("list_objects_v2")
        try:
            for page in paginator.paginate(Bucket=settings.AWS_STORAGE_BUCKET_NAME):
                # Empty pages don’t have a Contents key.
                if "Contents" in page:
                    client.delete_objects(
                        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                        Delete={"Objects": [{"Key": obj["Key"]} for obj in page["Contents"]]},
                    )
            client.delete_bucket(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
        except s3_client.exceptions.NoSuchBucket:
            pass


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
def django_test_environment_email_fixup(django_test_environment, settings) -> None:
    # Django forcefully sets the EMAIL_BACKEND to
    # "django.core.mail.backends.locmem.EmailBackend" in
    # django.test.utils.setup_test_environment.
    settings.EMAIL_BACKEND = "itou.emails.tasks.AsyncEmailBackend"
    settings.ASYNC_EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture(autouse=True, scope="session")
def itou_faker_provider(_session_faker):
    _session_faker.add_provider(faker_providers.ItouProvider)  # For faker
    Faker.add_provider(faker_providers.ItouProvider)  # For factory_boy


@pytest.fixture(autouse=True)
def django_ensure_matomo_titles(monkeypatch) -> None:
    is_running_on_ci = os.getenv("CI", False)
    if not is_running_on_ci:
        return

    from django.template import base, defaulttags, loader, loader_tags

    original_render = loader.render_to_string

    def assertive_render(template_name, context=None, request=None, using=None):
        if isinstance(template_name, list | tuple):
            template = loader.select_template(template_name, using=using)
        else:
            template = loader.get_template(template_name, using=using)

        def _walk_template_nodes(nodelist, condition_fn):
            for node in nodelist:
                if isinstance(node, loader_tags.ExtendsNode | defaulttags.IfNode):
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


@pytest.fixture(autouse=True, scope="function")
def unknown_variable_template_error(monkeypatch, request):
    marker = request.keywords.get("ignore_unknown_variable_template_error", None)
    if os.environ.get(INVALID_TEMPLATE_VARS_ENV, "false") == "true":
        # debug can be injected by django.template.context_processors.debug
        # user can be injected by django.contrib.auth.context_processors.auth
        # TODO(xfernandez): remove user from allow list (and remove the matching processor ?)
        BASE_IGNORE_LIST = {"debug", "user"}
        strict = True
        if marker is None:
            ignore_list = BASE_IGNORE_LIST
        elif marker.args:
            ignore_list = BASE_IGNORE_LIST | set(marker.args)
        else:
            # Marker without list
            strict = False

        if strict:
            origin_resolve = base_template.FilterExpression.resolve

            def stricter_resolve(self, context, ignore_failures=False):
                if (
                    self.is_var
                    and self.var.lookups is not None
                    and self.var.lookups[0] not in context
                    and self.var.lookups[0] not in ignore_list
                ):
                    ignore_failures = False
                return origin_resolve(self, context, ignore_failures)

            monkeypatch.setattr(base_template.FilterExpression, "resolve", stricter_resolve)


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


@pytest.fixture(scope="session", autouse=True)
def fix_unstable_annotation_order():
    """
    Patch Django’s ORM to have the annotation stable in the SQL produced by .count() calls.

    The annotation_mask order is then used in annotation_select property
    cf https://github.com/django/django/blob/stable/5.0.x/django/db/models/sql/query.py#L2519

    This patch however will stop working with https://github.com/django/django/commit/65ad4ade74d

    """
    from django.db.models.sql.query import Query

    patchy.patch(
        Query.get_aggregation,
        """\
        @@ -104,7 +104,7 @@
                         for annotation_alias, annotation in self.annotation_select.items():
                             if annotation.get_group_by_cols():
                                 annotation_mask.add(annotation_alias)
        -                inner_query.set_annotation_mask(annotation_mask)
        +                inner_query.set_annotation_mask(sorted(annotation_mask))

                 # Add aggregates to the outer AggregateQuery. This requires making
                 # sure all columns referenced by the aggregates are selected in the
                """,
    )


@pytest.fixture
def pdf_file():
    with open("tests/data/empty.pdf", "rb") as pdf:
        yield pdf


@pytest.fixture
def xlsx_file():
    with open("tests/data/empty.xlsx", "rb") as xlsx:
        yield xlsx


# SFTP related fixtures
# ------------------------------------------------------------------------------
class Server(paramiko.ServerInterface):
    def check_auth_password(self, *args, **kwargs):
        # all are allowed
        return paramiko.AUTH_SUCCESSFUL

    def check_channel_request(self, *args, **kwargs):
        return paramiko.OPEN_SUCCEEDED


class RootedSFTPServer(paramiko.SFTPServerInterface):
    """Taken and adapted from https://github.com/paramiko/paramiko/blob/main/tests/_stub_sftp.py"""

    def __init__(self, server: ServerInterface, *args, root_path, **kwargs):
        self._root_path = root_path
        super().__init__(server, *args, **kwargs)

    def _realpath(self, path):
        return str(self._root_path) + self.canonicalize(path)

    def list_folder(self, path):
        path = self._realpath(path)
        try:
            out = []
            for file_name in os.listdir(path):
                attr = paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(path, file_name)))
                attr.filename = file_name
                out.append(attr)
            return out
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def stat(self, path):
        try:
            return paramiko.SFTPAttributes.from_stat(os.stat(self._realpath(path)))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def open(self, path, flags, attr):
        path = self._realpath(path)

        flags = flags | getattr(os, "O_BINARY", 0)
        mode = getattr(attr, "st_mode", None) or 0o777
        try:
            fd = os.open(path, flags, mode)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

        if (flags & os.O_CREAT) and (attr is not None):
            attr._flags &= ~attr.FLAG_PERMISSIONS
            paramiko.SFTPServer.set_file_attr(path, attr)

        if flags & os.O_WRONLY:
            mode_from_flags = "a" if flags & os.O_APPEND else "w"
        elif flags & os.O_RDWR:
            mode_from_flags = "a+" if flags & os.O_APPEND else "r+"
        else:
            mode_from_flags = "r"  # O_RDONLY (== 0)
        try:
            f = os.fdopen(fd, mode_from_flags + "b")
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

        handle = paramiko.SFTPHandle(flags)
        handle.filename = path
        handle.readfile = f
        handle.writefile = f
        return handle

    def remove(self, path):
        try:
            os.remove(self._realpath(path))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK


@pytest.fixture(scope="session", name="sftp_host_key")
def sftp_host_key_fixture():
    # Use a 1024-bits key otherwise we get an OpenSSLError("digest too big for rsa key")
    return (
        rsa.generate_private_key(key_size=1024, public_exponent=65537)
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )


@pytest.fixture(name="sftp_directory")
def sftp_directory_fixture(tmp_path_factory):
    return tmp_path_factory.mktemp("sftp")


@pytest.fixture(name="sftp_client_factory")
def sftp_client_factory_fixture(sftp_host_key, sftp_directory):
    """
    Set up an in-memory SFTP server thread. Return the client Transport/socket.

    The resulting client Transport (along with all the server components) will
    be the same object throughout the test session; the `sftp_client_factory` fixture then
    creates new higher level client objects wrapped around the client Transport, as necessary.
    """
    # Sockets & transports
    server_socket, client_socket = socket.socketpair()
    server_transport = paramiko.Transport(server_socket)
    client_transport = paramiko.Transport(client_socket)

    # Auth
    server_transport.add_server_key(paramiko.RSAKey.from_private_key(io.StringIO(sftp_host_key)))

    # Server setup
    server_transport.set_subsystem_handler("sftp", paramiko.SFTPServer, RootedSFTPServer, root_path=sftp_directory)
    # The event parameter is here to not block waiting for a client connection
    server_transport.start_server(event=threading.Event(), server=Server())

    client_transport.connect(username="user", password="password")

    def sftp_client_factory(*args, **kwargs):
        return paramiko.SFTPClient.from_transport(client_transport)

    return sftp_client_factory


@pytest.fixture
def profile_login(client):
    def login(profile, job_application):
        if profile == "employer":
            client.force_login(job_application.to_company.members.first())
        elif profile == "prescriber":
            client.force_login(job_application.sender_prescriber_organization.members.first())
        elif profile == "job_seeker":
            client.force_login(job_application.job_seeker)
        else:
            raise ValueError(f"Invalid profile: '{profile}'")

    return login
