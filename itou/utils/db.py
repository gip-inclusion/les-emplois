import binascii
import contextlib
import logging

from django.db import connection
from django.db.models import Q
from psycopg import sql


logger = logging.getLogger(__name__)


def or_queries(queries, required=True):
    if required and not queries:
        raise ValueError("Filter queries must not be empty.")
    return Q.create(queries, connector=Q.OR)


def dictfetchall(cursor):
    """
    Return all rows from a cursor as a dict.
    Assume the column names are unique.

    Source: https://docs.djangoproject.com/en/dev/topics/db/sql/#executing-custom-sql-directly
    """
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


@contextlib.contextmanager
def set_runtime_parameter(parameter, value):
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL(f"SHOW {parameter}").format(parameter=sql.Identifier(parameter)))
        [original_value_row] = cursor.fetchall()
        [original_value] = original_value_row

        set_parameter_sql = sql.SQL(f"SET SESSION {parameter} TO {value}")
        cursor.execute(set_parameter_sql.format(parameter=sql.Identifier(parameter), value=value))
        yield
        cursor.execute(set_parameter_sql.format(parameter=sql.Identifier(parameter), value=original_value))


def statement_timeout(timeout):
    return set_runtime_parameter("statement_timeout", timeout)


def lock_timeout(timeout):
    return set_runtime_parameter("lock_timeout", timeout)


@contextlib.contextmanager
def pg_advisory_lock(name):
    lock_id = binascii.crc32(name.encode())
    logger.info("Acquiring advisory lock for %s (lock id %s).", name, lock_id)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
        yield
        cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
    logger.info("Releasing advisory lock for %s (lock id %s).", name, lock_id)
