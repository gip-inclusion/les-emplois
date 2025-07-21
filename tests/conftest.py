import collections
import copy
import datetime
import inspect
import io
import json
import os
import socket
import threading
import uuid
from functools import reduce

# Workaround being able to use freezegun with pandas.
# https://github.com/spulec/freezegun/issues/98
import pandas  # noqa F401
import paramiko
import patchy
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.gis.db.models.fields import get_srid_info
from django.core import management
from django.core.cache import caches
from django.core.files.storage import storages
from django.core.management import call_command
from django.db import connection
from django.template import base as base_template
from django.test import override_settings
from factory import Faker
from paramiko import ServerInterface
from slippers.templatetags.slippers import AttrsNode


# Rewrite before importing itou code.
pytest.register_assert_rewrite("tests.utils.test", "tests.utils.htmx.test")

from itou.utils import faker_providers  # noqa: E402
from itou.utils.cache import UnclearableCache  # noqa: E402
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
def preload_country_france(django_db_setup, django_db_blocker):
    from itou.asp.models import Country

    with django_db_blocker.unblock():
        Country.france_id


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

    caches["failsafe"].set(CACHE_ACTIVE_ANNOUNCEMENTS_KEY, None, None)
    yield
    caches["failsafe"].delete(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)


@pytest.fixture
def empty_active_announcements_cache(cached_announce_campaign):
    from itou.communications.cache import CACHE_ACTIVE_ANNOUNCEMENTS_KEY

    caches["failsafe"].delete(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)
    yield


@pytest.fixture
def failing_cache():
    with socket.create_server(("localhost", 0)) as s:
        empty_port = s.getsockname()[1]
        s.close()
        cache = UnclearableCache(
            f"redis://localhost:{empty_port}",
            {
                "OPTIONS": {
                    "CLIENT_CLASS": "itou.utils.cache.FailSafeRedisCacheClient",
                },
            },
        )
        yield cache


@pytest.fixture(name="temporary_bucket_name", autouse=True)
def temporary_bucket_name_fixture(monkeypatch):
    bucket_name = f"tests-{uuid.uuid4()}"
    with override_settings(AWS_STORAGE_BUCKET_NAME=bucket_name, PILOTAGE_DATASTORE_S3_BUCKET_NAME=bucket_name):
        for storage in {"default", "public"}:
            monkeypatch.setattr(storages[storage], "bucket_name", settings.AWS_STORAGE_BUCKET_NAME)
            monkeypatch.setattr(storages[storage], "_bucket", None)
        yield bucket_name


@pytest.fixture
def temporary_bucket(temporary_bucket_name):
    call_command("configure_bucket")
    yield
    client = s3_client()
    paginator = client.get_paginator("list_object_versions")
    try:
        for page in paginator.paginate(Bucket=settings.AWS_STORAGE_BUCKET_NAME):
            objects_to_delete = page.get("DeleteMarkers", []) + page.get("Versions", [])
            client.delete_objects(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Delete={
                    "Objects": [
                        {
                            "Key": obj["Key"],
                            "VersionId": obj["VersionId"],
                        }
                        for obj in objects_to_delete
                    ]
                },
            )
        client.delete_bucket(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
    except client.exceptions.NoSuchBucket:
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
    from django.template import base, defaulttags, loader_tags
    from django.template.backends.django import Template

    original_render = Template.render

    def assertive_render(self, context=None, request=None):
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

        title_node = _walk_template_nodes(self.template.nodelist, is_title_node)
        if title_node:
            var_node = _walk_template_nodes(title_node.nodelist, is_variable_node)
            if var_node and "matomo_custom_title" not in context:
                raise AssertionError(
                    f"template={self.origin} uses a variable title; "
                    "please provide a `matomo_custom_title` in the context!"
                )
        return original_render(self, context, request)

    monkeypatch.setattr(Template, "render", assertive_render)


def _fail_for_invalid_template_variable(var):
    stack = inspect.stack()

    origin = None
    for frame_info in stack[2:]:
        if frame_info.function == "render":
            try:
                render_self = frame_info.frame.f_locals["self"]
            except KeyError:
                continue
            else:
                if isinstance(render_self, AttrsNode):
                    # Escape hatch for AttrsNode, which adds attributes to a tag
                    # if the matching variables are defined.
                    return ""

            try:
                origin = render_self.origin
            except AttributeError:
                continue
            if origin is not None:
                break
    if origin is None:
        # finding the ``render`` needle in the stack
        frameinfo = reduce(lambda x, y: y if y.function == "render" and "base.py" in y.filename else x, stack)
        template = frameinfo.frame.f_locals["self"]
        if isinstance(template, base_template.Template):
            origin = template.name

    if origin:
        msg = f"Undefined template variable '{var}' in '{origin}'"
    else:
        msg = f"Undefined template variable '{var}'"
    pytest.fail(msg)


@pytest.fixture(autouse=True, scope="session")
def _fail_for_invalid_template_variable_improved(_fail_for_invalid_template_variable):
    patchy.patch(
        base_template.FilterExpression.resolve,
        """\
            @@ -7,11 +7,10 @@
                             obj = None
                         else:
                             string_if_invalid = context.template.engine.string_if_invalid
            -                if string_if_invalid:
            -                    if "%s" in string_if_invalid:
            -                        return string_if_invalid % self.var
            -                    else:
            -                        return string_if_invalid
            +                from django.template.defaultfilters import default as default_filter
            +                if default_filter not in {func for func, _args in self.filters}:
            +                    from tests.conftest import _fail_for_invalid_template_variable
            +                    obj = _fail_for_invalid_template_variable(self.var)
                             else:
                                 obj = string_if_invalid
                 else:
        """,
    )


@pytest.fixture(autouse=True, scope="function")
def unknown_variable_template_error(monkeypatch, request):
    marker = request.keywords.get("ignore_unknown_variable_template_error", None)
    ignore_list = set()
    if marker and marker.args:
        ignore_list.update(marker.args)

    origin_resolve = base_template.FilterExpression.resolve

    seen_variables = set()

    def stricter_resolve(self, context, ignore_failures=False):
        if self.is_var and self.var.lookups is not None:
            seen_variables.add(self.var.lookups[0])
            if self.var.lookups[0] not in context and self.var.lookups[0] not in ignore_list:
                ignore_failures = False
        return origin_resolve(self, context, ignore_failures)

    monkeypatch.setattr(base_template.FilterExpression, "resolve", stricter_resolve)
    yield

    ignored_variable_not_seen = ignore_list - seen_variables
    if ignored_variable_not_seen:
        pytest.fail(f"Unnecessary usage of 'ignore_unknown_variable_template_error' for: {ignored_variable_not_seen}")


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
def warn_select_for_update_with_select_related():
    """
    To avoid accidentally locking all rows in a join with select_for_update,
    enforce usage of the `of` keyword argument to `select_for_update`.
    """
    from django.db.models.sql.compiler import SQLCompiler

    # Django maintains the joins in alias_map.
    patchy.patch(
        SQLCompiler.as_sql,
        """\
        @@ -105,6 +105,12 @@
                         skip_locked = self.query.select_for_update_skip_locked
                         of = self.query.select_for_update_of
                         no_key = self.query.select_for_no_key_update
        +                if self.query.select_related and not of:
        +                    raise TypeError(
        +                       "select_for_update(of=...) must be specified "
        +                       "to avoid locking relations unexpectedly when "
        +                       "select_related is used."
        +                    )
                         # If it's a NOWAIT/SKIP LOCKED/OF/NO KEY query but the
                         # backend doesn't support it, raise NotSupportedError to
                         # prevent a possible deadlock.
        """,
    )


@pytest.fixture(scope="session", autouse=True)
def strict_excel_rendering():
    from xlsx_streaming.render import update_cell

    patchy.patch(
        update_cell,
        """\
        @@ -13,10 +13,5 @@
                 'b': _update_boolean_cell,
             }.get(cell_type, _update_text_cell)

        -    try:
        -        update_function(cell, value)
        -    except Exception as e:  # pylint: disable=broad-except
        -        args = e.args or ['']
        -        msg = f"(column '{column}', line '{line}') data does not match template: {args[0]}"
        -        logger.debug(msg)
        +    update_function(cell, value)
             cell.set('r', f'{column}{line}')
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


## Mockers
@pytest.fixture(name="sentry_respx_mock")
def sentry_respx_mock_fixture(respx_mock):
    json = {
        "data": [
            {
                "tuple(('duration', 300))": [["duration", 300]],
                "apdex()": 0.9556246545071905,
                "failure_rate()": 0.08123341283760084,
                "project_threshold_config": ["duration", 300],
            }
        ],
        "meta": {
            "fields": {
                "tuple(('duration', 300))": "string",
                "apdex()": "number",
                "failure_rate()": "percentage",
                "project_threshold_config": "string",
            },
            "units": {
                "tuple(('duration', 300))": None,
                "apdex()": None,
                "failure_rate()": None,
                "project_threshold_config": None,
            },
            "isMetricsData": False,
            "isMetricsExtractedData": False,
            "tips": {"query": None, "columns": None},
            "datasetReason": "unchanged",
            "dataset": "discover",
        },
    }

    end = datetime.datetime(2024, 12, 3, 0, 0, 0, tzinfo=datetime.UTC)
    start = end - relativedelta(days=1)
    params = {
        "query": '(event.type:"transaction")',
        "project": settings.API_SENTRY_PROJECT_ID,
        "field": ["apdex()", "failure_rate()"],
        "start": start.isoformat(),
        "end": end.isoformat(),
    }

    url = f"{settings.API_SENTRY_BASE_URL}/organizations/{settings.API_SENTRY_ORG_NAME}/events/"
    return start, respx_mock.route(
        method="GET", params=params, url=url, headers={"Authorization": f"Bearer {settings.API_SENTRY_STATS_TOKEN}"}
    ).respond(json=json)


@pytest.fixture(autouse=True, scope="session")
def detect_silent_date_cast():
    from django.db.models import DateField

    original_pre_save = DateField.pre_save

    def strict_pre_save(self, model_instance, add):
        # DateTimeField inherits DateField, hence the check on self.__class__
        if self.__class__ is DateField and isinstance(getattr(model_instance, self.attname), datetime.datetime):
            raise ValueError(
                f"<{model_instance}>.{self.attname}={getattr(model_instance, self.attname)} needs to be a date"
            )
        return original_pre_save(self, model_instance, add)

    DateField.pre_save = strict_pre_save


@pytest.fixture(autouse=True, scope="session")
def detect_missing_auto_now_in_update_fields():
    from django.apps import apps
    from django.db.models import Model

    auto_now_fields = collections.defaultdict(list)
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if getattr(field, "auto_now", False):
                auto_now_fields[model._meta.label].append(field.name)

    original_save = Model.save

    def strict_save(self, *args, update_fields=None, **kwargs):
        if update_fields:
            for auto_now_field in auto_now_fields[self._meta.label]:
                if auto_now_field not in update_fields:
                    raise ValueError(f"Calling save with update_fields without {auto_now_field}")
        return original_save(self, *args, update_fields=update_fields, **kwargs)

    Model.save = strict_save


@pytest.fixture(name="updown_respx_mock")
def updown_respx_mock_fixture(respx_mock):
    json = {
        "uptime": 100.0,
        "apdex": 0.986,
        "timings": {"redirect": 148, "namelookup": 1, "connection": 22, "handshake": 25, "response": 99, "total": 295},
        "requests": {
            "samples": 44214,
            "failures": 12,
            "satisfied": 43256,
            "tolerated": 664,
            "by_response_time": {
                "under125": 42383,
                "under250": 42874,
                "under500": 43256,
                "under1000": 43620,
                "under2000": 43920,
                "under4000": 44100,
                "under8000": 44183,
                "under16000": 44201,
                "under32000": 44202,
            },
        },
    }
    end = datetime.datetime(2024, 12, 3, 0, 0, 0, tzinfo=datetime.UTC)
    start = end - relativedelta(days=1)
    params = {
        "api-key": settings.API_UPDOWN_TOKEN,
        "from": start.isoformat(),
        "to": end.isoformat(),
    }
    headers = {
        "Content-Type": "application/json",
    }

    url = f"{settings.API_UPDOWN_BASE_URL}/checks/{settings.API_UPDOWN_CHECK_ID}/metrics/"
    return start, respx_mock.route(headers=headers, method="GET", params=params, url=url).respond(json=json)


@pytest.fixture(name="github_respx_mock")
def github_respx_mock_fixture(respx_mock):
    with open(os.path.join(settings.ROOT_DIR, "tests", "data", "github.json")) as file:
        resp_json = json.load(file)

    start = datetime.datetime(2024, 12, 2, tzinfo=datetime.UTC)
    params = {
        "labels": ["bug"],
        "state": "closed",
        "pulls": True,
        "per_page": 100,
        "since": start.isoformat(),  # The GH API does not allow an end date.
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    url = f"{settings.API_GITHUB_BASE_URL}/repos/gip-inclusion/les-emplois/issues"
    return start, respx_mock.route(headers=headers, method="GET", params=params, url=url).respond(json=resp_json)


@pytest.fixture(name="pro_connect")
def setup_pro_connect():
    # this import requirest the settings to be loaded so we con't put it with the others
    from tests.openid_connect.pro_connect.test import pro_connect_setup

    with pro_connect_setup():
        yield pro_connect_setup


@pytest.fixture(autouse=True, scope="session")
def detect_missing_csrf_token():
    from django.template.defaulttags import CsrfTokenNode

    origin_render = CsrfTokenNode.render

    def render(self, context):
        if context.get("csrf_token") is None:
            pytest.fail(f"Missing csrf_token variable: {self.origin}")
        return origin_render(self, context)

    CsrfTokenNode.render = render
