import binascii
import contextlib
import logging

from django.db import connection
from django.db.models import Q


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
def statement_timeout(timeout):
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        [original_statement_timeout_row] = cursor.fetchall()
        [original_statement_timeout] = original_statement_timeout_row

        cursor.execute("SET SESSION statement_timeout TO %s", (timeout,))
        yield
        cursor.execute("SET SESSION statement_timeout TO %s", (original_statement_timeout,))


@contextlib.contextmanager
def pg_advisory_lock(name):
    lock_id = binascii.crc32(name.encode())
    logger.info("Acquiring advisory lock for %s (lock id %s).", name, lock_id)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
        yield
        cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
    logger.info("Releasing advisory lock for %s (lock id %s).", name, lock_id)
