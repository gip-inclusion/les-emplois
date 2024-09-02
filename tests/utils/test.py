import importlib
import inspect
import io
import linecache
import os.path
import random
import re
from contextlib import contextmanager

import openpyxl
import sqlparse
from bs4 import BeautifulSoup
from django.conf import Path, settings
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.backends.utils import CursorDebugWrapper
from django.template import Template
from django.template.base import Node
from django.template.loader import render_to_string
from django.test import Client, TestCase as BaseTestCase
from django.test.utils import CaptureQueriesContext, TestContextDecorator
from pytest_django.asserts import assertContains, assertNotContains

from itou.common_apps.address.departments import DEPARTMENTS


# SAVEPOINT + RELEASE from the ATOMIC_REQUESTS transaction
BASE_NUM_QUERIES = 2


def pprint_html(response, **selectors):
    """
    Pretty-print HTML responses (or fragment selected with :arg:`selector`)

    Heed the warning from
    https://www.crummy.com/software/BeautifulSoup/bs4/doc/#pretty-printing :

    > Since it adds whitespace (in the form of newlines), prettify() changes
      the meaning of an HTML document and should not be used to reformat one.
      The goal of prettify() is to help you visually understand the structure
      of the documents you work with.

    Use `snapshot`s, `assertHTMLEqual` and `assertContains(…, html=True)` to
    make assertions.
    """
    parser = BeautifulSoup(response.content, "html5lib")
    print("\n\n".join([elt.prettify() for elt in parser.find_all(**selectors)]))


def remove_static_hash(content):
    return re.sub(r"\.[\da-f]{12}\.svg\b", ".svg", content)


def parse_response_to_soup(response, selector=None, no_html_body=False, replace_in_attr=None):
    soup = BeautifulSoup(response.content, "html5lib", from_encoding=response.charset or "utf-8")
    if no_html_body:
        # If the provided HTML does not contain <html><body> tags
        # html5lib will always add them around the response:
        # ignore them
        soup = soup.body
    if selector is not None:
        [soup] = soup.select(selector)
    title = soup.title
    if title:
        title.string = re.sub(r"\s+", " ", title.string)
    for csrf_token_input in soup.find_all("input", attrs={"name": "csrfmiddlewaretoken"}):
        csrf_token_input["value"] = "NORMALIZED_CSRF_TOKEN"
    if "nonce" in soup.attrs:
        soup["nonce"] = "NORMALIZED_CSP_NONCE"
    for csp_nonce_script in soup.find_all("script", {"nonce": True}):
        csp_nonce_script["nonce"] = "NORMALIZED_CSP_NONCE"
    for img in soup.find_all("img", attrs={"src": True}):
        img["src"] = remove_static_hash(img["src"])
    if replace_in_attr:
        replacements = [
            (
                replacement
                if isinstance(replacement, tuple)
                else ("href", str(replacement.pk), f"[PK of {type(replacement).__name__}]")
            )
            for replacement in replace_in_attr
        ]

        # Get the list of the attrs (deduplicated) we should search for replacement
        unique_attrs = set([replace_tuple[0] for replace_tuple in replacements])

        for attr in unique_attrs:
            # Search and replace in descendant nodes
            for links in soup.find_all(attrs={attr: True}):
                for _, from_str, to_str in replacements:
                    links.attrs.update({f"{attr}": links.attrs[attr].replace(from_str, to_str)})
            # Also replace attributes in the top node
            if attr in soup.attrs:
                for _, from_str, to_str in replacements:
                    soup.attrs.update({f"{attr}": soup.attrs[attr].replace(from_str, to_str)})
    return soup


class NoInlineClient(Client):
    def request(self, **request):
        response = super().request(**request)
        content_type = response["Content-Type"].split(";")[0]
        if content_type == "text/html" and response.content:
            content = response.content.decode(response.charset)
            assert " onclick=" not in content
            assert " onbeforeinput=" not in content
            assert " onbeforeinput=" not in content
            assert " onchange=" not in content
            assert " oncopy=" not in content
            assert " oncut=" not in content
            assert " ondrag=" not in content
            assert " ondragend=" not in content
            assert " ondragenter=" not in content
            assert " ondragleave=" not in content
            assert " ondragover=" not in content
            assert " ondragstart=" not in content
            assert " ondrop=" not in content
            assert " oninput=" not in content
            assert "<script>" not in content
        return response


class ItouClient(NoInlineClient):
    def request(self, *args, **kwargs):
        with TestCase.captureOnCommitCallbacks(execute=True):
            return super().request(*args, **kwargs)


class TestCase(BaseTestCase):
    client_class = ItouClient


class reload_module(TestContextDecorator):
    def __init__(self, module):
        self._module = module
        self._original_values = {key: getattr(module, key) for key in dir(module) if not key.startswith("__")}
        super().__init__()

    def enable(self):
        importlib.reload(self._module)

    def disable(self):
        for key, value in self._original_values.items():
            setattr(self._module, key, value)


def get_rows_from_streaming_response(response):
    """Helper to read streamed XLSX files in tests"""

    content = b"".join(response.streaming_content)
    workbook = openpyxl.load_workbook(io.BytesIO(content))
    worksheet = workbook.active
    return [[cell.value or "" for cell in row] for row in worksheet.rows]


def assert_previous_step(response, url, back_to_list=False):
    previous_step = render_to_string("layout/previous_step.html", {"back_url": url})
    if back_to_list:
        assertContains(response, "Retour à la liste")
    else:
        assertNotContains(response, "Retour à la liste")
    assertContains(response, previous_step)


def create_fake_postcode():
    department = random.choice(list(DEPARTMENTS))
    if department == "2A":
        department = random.choice(["200", "201", "207"])
    elif department == "2B":
        department = random.choice(["202", "204", "206"])
    # Corsica and some DROM-COM department being 3 digits long,
    # return value may be longer than 5. Cut it.
    return f"{department}{int(random.randint(0, 999)):03}"[:5]


class _AssertSnapshotQueriesContext(CaptureQueriesContext):
    def __init__(self, snapshot, connection):
        self.snapshot = snapshot
        super().__init__(connection)

    def normalize_sql(self, sql):
        if re.match(r'^SAVEPOINT +".+?" *$', sql):
            # 'SAVEPOINT "s124109847980928_x70"'
            return 'SAVEPOINT "<snapshot>"'
        if re.match(r'^RELEASE +SAVEPOINT +".+?" *$', sql):
            # 'RELEASE SAVEPOINT "s124109847980928_x69"'
            return 'RELEASE SAVEPOINT "<snapshot>"'
        return sqlparse.format(
            sql,
            keyword_case="upper",
            reindent=True,
            reindent_align=True,
            use_space_around_operators=True,
        )

    def build_snapshot(self, queries):
        return {
            "num_queries": len(queries),
            "queries": [
                {
                    "sql": self.normalize_sql(query["raw_sql"]),
                    "origin": query["origin"],
                }
                for query in queries
            ],
        }

    def __exit__(self, exc_type, exc_value, traceback):
        super().__exit__(exc_type, exc_value, traceback)
        if exc_type is not None:
            return
        new_snapshot = self.build_snapshot(self.captured_queries)
        assert new_snapshot == self.snapshot
        for item in new_snapshot["queries"]:
            assert item["origin"], f"origin is mandatory and missing for {item}"


def assertSnapshotQueries(snapshot, func=None, *args, using=DEFAULT_DB_ALIAS, **kwargs):
    conn = connections[using]

    context = _AssertSnapshotQueriesContext(snapshot, conn)
    if func is None:
        return context

    with context:
        func(*args, **kwargs)


origin_debug_sql = CursorDebugWrapper.debug_sql


# List of functions that help identify the query origin
OTHER_PACKAGES_ALLOWLIST = {
    "first": "django/db/models/query.py",
    "get_object": ("django/views/generic/detail.py",),
    "_get_session_from_db": ("django/contrib/sessions/backends/db.py",),
    "__enter__": ("django/db/transaction.py",),
    "__exit__": ("django/db/transaction.py",),
    "save": ("django/contrib/sessions/backends/db.py",),
}


def normalized_frame_filename(frame_info, debug):
    """If the frame needs to be included, return its normalized filename, or None otherwise"""
    frame_filename = frame_info.filename
    if frame_filename.startswith(settings.APPS_DIR):
        return os.path.relpath(frame_filename, settings.APPS_DIR)
    if (
        (allowed_filepaths := OTHER_PACKAGES_ALLOWLIST.get(frame_info.function))
        and frame_filename.endswith(allowed_filepaths)
        or debug
    ):
        if "site-packages" in frame_filename:
            return f'<site-packages>{frame_filename.split("site-packages", 1)[1]}'
        elif debug:
            return frame_filename


def get_template_source_from_exception_info(node: Node, context) -> tuple[int, str]:
    # Taken from django-debug-toolbar
    if context.template.origin == node.origin:
        exception_info = context.template.get_exception_info(Exception("DDT"), node.token)
    else:
        exception_info = context.render_context.template.get_exception_info(Exception("DDT"), node.token)
    return exception_info["line"], exception_info["name"]


def _detect_origin(debug=False):
    parts = []
    # Ignore first 3 frames:
    # - tests/utils/test.py::_detect_origin
    # - tests/utils/test.py::debug_sql
    # - <python>::contextlib.py::__exit__
    for frame_info in inspect.stack()[3:]:
        frame_filename = frame_info.filename

        if frame_info.function == "pytest_pyfunc_call" and "_pytest" in frame_filename:
            # We are now in pytest machinery, no need to inspect frames anymore
            break

        template_origin = None
        template_debug_info = None
        if frame_info.function == "render" and "django/template" in frame_filename:
            try:
                frame_self = frame_info.frame.f_locals["self"]
            except KeyError:
                pass
            else:
                if isinstance(frame_self, Node):
                    try:
                        frame_context = frame_info.frame.f_locals["context"]
                    except KeyError:
                        pass
                    else:
                        class_name = type(frame_self).__name__
                        template_origin = f"{class_name}[{frame_self.origin.template_name}]"
                        # This requires the engine to be in debug mode
                        if debug:
                            template_debug_info = get_template_source_from_exception_info(frame_self, frame_context)

        if template_origin is not None:
            parts.append(template_origin)
            if debug and template_debug_info:
                parts.append(
                    f"  Line: {template_debug_info[0]} - "
                    + linecache.getline(template_debug_info[1], template_debug_info[0]).strip()
                )
        elif normalized_filename := normalized_frame_filename(frame_info, debug):
            if not debug and "get_response(request)" in linecache.getline(frame_filename, frame_info.lineno):
                # Middleware passing the request to the next: useless as an origin
                continue
            if "self" in frame_info.frame.f_locals:
                class_name = type(frame_info.frame.f_locals["self"]).__name__
                function = f"{class_name}.{frame_info.function}"
            else:
                function = frame_info.function
            parts.append(f"{function}[{normalized_filename}]")
            if debug:
                parts.append(
                    f"  Line: {frame_info.lineno} - " + linecache.getline(frame_filename, frame_info.lineno).strip()
                )
    return parts


@contextmanager
def debug_sql(self, sql=None, params=None, use_last_executed_query=False, many=False):
    with origin_debug_sql(self, sql, params, use_last_executed_query, many):
        yield
    # Enrich last query
    last_query = self.db.queries_log[-1]
    last_query["raw_sql"] = sql
    last_query["origin"] = _detect_origin(debug=bool(os.getenv("DEBUG_SQL_SNAPSHOT")))


CursorDebugWrapper.debug_sql = debug_sql


def load_template(path):
    return Template((Path("itou/templates") / path).read_text())
