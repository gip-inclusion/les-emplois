import json

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory
from pytest_django.asserts import assertNumQueries

from itou.utils import triggers
from itou.utils.triggers.middleware import fields_history


def test_middleware():
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    with assertNumQueries(0):
        fields_history(lambda _: HttpResponse())(request)


@pytest.mark.parametrize("context", [{}, {"key": "value"}], ids=["empty", "non-empty"])
def test_context(context):
    with triggers.context(**context):
        with assertNumQueries(2), connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('itou.context')")
            assert cursor.fetchone() == (json.dumps(context),)


def test_context_when_it_is_never_set():
    with assertNumQueries(1), connection.cursor() as cursor:
        # Can't use `current_setting()` because the setting could already exist as a placeholder because of a
        # previous test, so sometimes we will get a django.ProgrammingError / psycopg.UndefinedObject
        # and other time just an empty string.
        cursor.execute("SELECT 1")
