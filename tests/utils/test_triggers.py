import json
import uuid

import pytest
from django.db import connection
from pytest_django.asserts import assertNumQueries

from itou.utils import triggers


@pytest.mark.parametrize("context", [{}, {"key": "value"}], ids=["empty", "non-empty"])
def test_context(context):
    with assertNumQueries(2):
        with triggers.context(**context), connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('itou.context')")
            assert cursor.fetchone() == (json.dumps(context),)


def test_context_stacking():
    with assertNumQueries(6), connection.cursor() as cursor:
        context_1 = {"level": 1}
        with triggers.context(**context_1):
            cursor.execute("SELECT current_setting('itou.context')")
            assert cursor.fetchone() == (json.dumps(context_1),)

            context_2 = {"level": 1, "sublevel": 1}
            with triggers.context(**context_2):
                cursor.execute("SELECT current_setting('itou.context')")
            assert cursor.fetchone() == (json.dumps(context_2),)

            cursor.execute("SELECT current_setting('itou.context')")
            assert cursor.fetchone() == (json.dumps(context_1),)


def test_context_with_same_data():
    expected = {"uuid": str(uuid.uuid4())}
    with assertNumQueries(3), connection.cursor() as cursor:
        with triggers.context(**expected):
            cursor.execute("SELECT current_setting('itou.context')")
            assert cursor.fetchone() == (json.dumps(expected),)

            with triggers.context(**expected):
                cursor.execute("SELECT current_setting('itou.context')")
            assert cursor.fetchone() == (json.dumps(expected),)


def test_context_laziness():
    expected = {"uuid": str(uuid.uuid4())}
    with assertNumQueries(2), connection.cursor() as cursor:
        with triggers.context(**{"uuid": str(uuid.uuid4())}), triggers.context(**expected):
            cursor.execute("SELECT current_setting('itou.context')")
            assert cursor.fetchone() == (json.dumps(expected),)
