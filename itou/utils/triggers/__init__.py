import contextlib
import functools
import json
import operator
import threading
from typing import Any

from django.db import connection, models
from pgtrigger import Condition, core


_context = threading.local()
_context_is_up_to_date = threading.Event()
_context_query_in_progress = threading.Event()
_context_connection_wrapper_installed = threading.Event()


def _set_context_connection_wrapper(execute, *args, **kwargs):
    if not _context_is_up_to_date.is_set() and not _context_query_in_progress.is_set():
        with connection.cursor() as cursor:
            _context_query_in_progress.set()
            try:
                cursor.execute(
                    "SELECT set_config('itou.context', %s, true)",
                    [json.dumps(_context.data)],
                )
            finally:
                _context_query_in_progress.clear()
        _context_is_up_to_date.set()

    return execute(*args, **kwargs)


@contextlib.contextmanager
def context(**kwargs):
    previous_data, _context.data = (
        getattr(_context, "data", None),
        kwargs,
    )  # FIXME: Should we merge instead of replace?
    _context_is_up_to_date.clear()

    with contextlib.ExitStack() as stack:
        if not _context_connection_wrapper_installed.is_set():
            stack.enter_context(connection.execute_wrapper(_set_context_connection_wrapper))
            _context_connection_wrapper_installed.set()
            stack.callback(_context_connection_wrapper_installed.clear)

        yield

    _context.data = previous_data
    _context_is_up_to_date.clear()


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
