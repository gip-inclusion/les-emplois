import contextlib
import functools
import json
import operator
import threading
from typing import Any

from django.db import connection, models
from pgtrigger import Condition, core


_context = threading.local()


def get_main_atomic_block(connection):
    # Find the outermost atomic block, ignoring the special one added by django around tests
    return next((atomic_block for atomic_block in connection.atomic_blocks if not atomic_block._from_testcase), None)


def _set_context_connection_wrapper(execute, sql, params, many, context):
    connection = context["connection"]
    main_atomic_block = get_main_atomic_block(connection)
    context_is_outdated = getattr(_context, "last_data_set", None) != getattr(_context, "data", None)
    if not context_is_outdated and getattr(_context, "data", None) is not None:
        context_is_outdated = getattr(_context, "last_atomic_block_set", None) != main_atomic_block
    if context_is_outdated and not connection.in_atomic_block:
        # If we aren't in a transaction then the context has already been flushed so we don't need
        # to call `set_config()` to empty it as `None` is the default sentinel value for `_context.data`.
        _context.last_data_set = None
        _context.last_atomic_block_set = None
        context_is_outdated = False
    if context_is_outdated:
        # Ideally we should set the last data *after* the completion of the query, but
        # doing it here prevent the connection wrapper to be called recursively without exit
        # condition or any other kind of synchronization because of the `set_config()` query.
        _context.last_data_set = getattr(_context, "data", None)
        _context.last_atomic_block_set = main_atomic_block
        # Store the empty string if no context is defined to avoid storing the 'null'
        # which is a valid JSON value that does not crash the trigger using the context
        sql_content = "" if _context.last_data_set is None else json.dumps(_context.last_data_set)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('itou.context', %s, true)",
                [sql_content],
            )

    return execute(sql, params, many, context)


# This is a context manager ready to be used
@contextlib.contextmanager
def connection_wrapper():
    assert _set_context_connection_wrapper not in connection.execute_wrappers, (
        "These context managers cannot be stacked"
    )
    try:
        with connection.execute_wrapper(_set_context_connection_wrapper):
            yield
    finally:
        if not connection.in_atomic_block or get_main_atomic_block(connection) is None:
            _context.last_data_set = None
            _context.last_atomic_block_set = None


@contextlib.contextmanager
def context(*, replace_existing: bool = False, **kwargs):
    if get_main_atomic_block(connection) is None:
        raise RuntimeError("Entering trigger context outside a transaction")
    if _set_context_connection_wrapper not in connection.execute_wrappers:
        raise RuntimeError("triggers.context called without _set_context_connection_wrapper in place")

    previous_data, _context.data = getattr(_context, "data", None), kwargs
    if not replace_existing and previous_data:
        _context.data = {**previous_data, **_context.data}
    try:
        yield
    finally:
        _context.data = previous_data


def get_current_context():
    return getattr(_context, "data", None)


@contextlib.contextmanager
def fake_context(**kwargs):
    # This should only be used in tests & is completely incompatible with concurrent uses
    # of _set_context_connection_wrapper
    assert _set_context_connection_wrapper not in connection.execute_wrappers
    context = {"fake_context": True, **kwargs}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('itou.context', %s, true)",
            [json.dumps(context)],
        )
        yield
        cursor.execute("SELECT set_config('itou.context', '', true)")


class FieldsHistory(core.Trigger):
    when: core.When = core.Before
    operation: core.Operation = core.Update
    declare: list[tuple[str, str]] | None = [("_rows_diff", "jsonb"), ("current_context", "jsonb")]
    fields: list[str] | None = None

    HISTORY_FIELD_NAME = "fields_history"

    def __init__(
        self,
        *,
        fields: list[str] | None = None,
        **kwargs: Any,
    ):
        self.fields = fields or self.fields

        if not self.fields:
            raise ValueError("Must provide at least one field")

        super().__init__(**kwargs)

    def get_condition(self, model: models.Model) -> Condition:
        fields = [model._meta.get_field(field).name for field in self.fields] + [self.HISTORY_FIELD_NAME]
        return functools.reduce(
            operator.or_,
            [core.Q(**{f"old__{field}__df": core.F(f"new__{field}")}) for field in fields],
        )

    def get_func(self, model):
        sql_history_field = model._meta.get_field(self.HISTORY_FIELD_NAME).column
        sql_fields = [model._meta.get_field(field).column for field in self.fields]
        return f"""
            IF NEW.{sql_history_field} IS DISTINCT FROM OLD.{sql_history_field} THEN
                RAISE EXCEPTION 'Modification du champ "{sql_history_field}" interdit';
            END IF;

            BEGIN
                -- Convert empty string to NULL, this happen when set_config() was called but not for the current
                -- transaction, this end with a 22P02/invalid_text_representation error as this is not valid JSON.
                SELECT NULLIF(current_setting('itou.context'), '') INTO current_context;
            EXCEPTION
                WHEN undefined_object THEN current_context := NULL;  -- set_config() was not called, ever.
            END;

            IF current_context IS NULL THEN
                RAISE EXCEPTION 'No context available';
            END IF;

            SELECT jsonb_build_object(
                'before', jsonb_object_agg(pre.key, pre.value),
                'after', jsonb_object_agg(post.key, post.value),
                '_timestamp', current_timestamp,
                '_context', current_context::jsonb
            )
            INTO _rows_diff
            FROM jsonb_each(to_jsonb(OLD)) AS pre
            CROSS JOIN jsonb_each(to_jsonb(NEW)) AS post
            WHERE pre.key = post.key
            AND pre.value IS DISTINCT FROM post.value
            AND pre.key IN ({",".join([f"'{field}'" for field in sql_fields])});

            NEW.{sql_history_field} = array_append(NEW.{sql_history_field}, _rows_diff);
            RETURN NEW;
        """
