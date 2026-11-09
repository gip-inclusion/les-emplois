import binascii
import contextlib
import inspect
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


def get_lock_id(name: str) -> int:
    return binascii.crc32(name.encode())


def check_connection_is_not_reused():
    # When CONN_MAX_AGE is not zero, the connection is reused. So if
    # the caller does not release a session-level lock, it will be
    # held and will leak to other users of the same session, for
    # example other HTTP requests. Let's not provide a tool that could
    # shoot ourselves in the foot.
    if connection.settings_dict.get("CONN_MAX_AGE") != 0:
        caller = inspect.currentframe().f_back.f_code.co_name
        raise ValueError(f"Cannot use `{caller}` with non-zero CONN_MAX_AGE")


class CannotAcquireLock(Exception):
    def __init__(self, lock_name, lock_id):
        self.lock_name = lock_name
        self.lock_id = lock_id
        super().__init__()

    def __str__(self):
        return f"Cannot acquire lock for {self.lock_name} (lock id {self.lock_id})"


def pg_try_advisory_lock(name: str):
    check_connection_is_not_reused()
    lock_id = get_lock_id(name)
    logger.info("Trying to acquire advisory lock for %s (lock id %s).", name, lock_id)
    with connection.cursor() as cursor:
        result = cursor.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,))
        row = result.fetchone()
        if not row[0]:
            raise CannotAcquireLock(name, lock_id)
    logger.info("Acquired advisory lock for %s (lock id %s).", name, lock_id)


@contextlib.contextmanager
def pg_advisory_lock(name: str):
    lock_id = get_lock_id(name)
    logger.info("Acquiring advisory lock for %s (lock id %s).", name, lock_id)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
        yield
        cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
    logger.info("Releasing advisory lock for %s (lock id %s).", name, lock_id)


class ExclusionViolationError(IntegrityError):
    pass


class UniqueViolationError(IntegrityError):
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
maybe_unique_violation = _maybe_constraint_violation(psycopg.errors.UniqueViolation, UniqueViolationError)
