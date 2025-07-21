import binascii
import contextlib
import logging

import psycopg.errors
from django.db import IntegrityError, ProgrammingError, connection, transaction
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


class ExclusionViolationError(IntegrityError):
    pass


def _maybe_constraint_violation(psycopg_error, exception_class):
    @contextlib.contextmanager
    def f(model, constraint_name):
        def find_constraint():
            for constraint in model._meta.constraints:
                if constraint.name == constraint_name:
                    return constraint
            raise ProgrammingError(
                f"No constraint named {constraint_name}, "
                f"choices are: {', '.join(c.name for c in model._meta.constraints)}"
            )

        try:
            # The integrity error will cause:
            #
            # An error occurred in the current transaction. You can't execute
            # queries until the end of the 'atomic' block.
            #
            # This inner atomic allows rolling back to the previous savepoint
            # in case of exception, and issuing SQL queries for the rest of the
            # view when a constraint has been violated.
            with transaction.atomic():
                yield
        except IntegrityError as e:
            psycopg_exception = e.__cause__
            if (
                isinstance(psycopg_exception, psycopg_error)
                and psycopg_exception.diag.constraint_name == constraint_name
            ):
                constraint = find_constraint()
                raise exception_class(constraint.get_violation_error_message()) from e
            raise

    return f


maybe_exclusion_violation = _maybe_constraint_violation(psycopg.errors.ExclusionViolation, ExclusionViolationError)
