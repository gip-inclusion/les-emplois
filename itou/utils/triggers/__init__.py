import contextlib
import functools
import json
import logging
import operator
import threading
from functools import wraps
from typing import Any

from django.conf import settings
from django.db import connection, models
from pgtrigger import Condition, core

from itou.utils.enums import ItouEnvironment


logger = logging.getLogger(__name__)


_context = threading.local()


def _set_context_connection_wrapper(execute, sql, params, many, context):
    context_is_outdated = getattr(_context, "last_data_set", None) != _context.data
    if context_is_outdated:
        if not context["connection"].in_atomic_block:
            # This should not happen since set_config is called with is_local=true
            error_msg = "Trying to define a context outside a transaction"
            if settings.ITOU_ENVIRONMENT in [ItouEnvironment.DEV, ItouEnvironment.TEST]:
                raise RuntimeError(error_msg)
            else:
                logger.error(error_msg)  # Notify issue to sentry
        # Ideally we should set the last data *after* the completion of the query, but
        # doing it here prevent the connection wrapper to be called recursively without exit
        # condition or any other kind of synchronization because of the `set_config()` query.
        _context.last_data_set = _context.data
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('itou.context', %s, true)",
                [json.dumps(_context.data)],
            )

    return execute(sql, params, many, context)


@contextlib.contextmanager
def context(*, replace_existing: bool = False, **kwargs):
    previous_data, _context.data = getattr(_context, "data", None), kwargs
    if not replace_existing and previous_data:
        _context.data = {**previous_data, **_context.data}

    if _set_context_connection_wrapper not in connection.execute_wrappers:
        cm = connection.execute_wrapper(_set_context_connection_wrapper)
    else:
        cm = contextlib.nullcontext()

    try:
        with cm:
            yield
    finally:
        _context.data, _context.last_data_set = previous_data, None


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


def request_context(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method in ["GET", "HEAD"]:
            return view_func(request, *args, **kwargs)

        base_context = {
            "user": request.user.pk if request.user.is_authenticated else None,
            "request_id": request.request_id if hasattr(request, "request_id") else None,
        }

        with context(**base_context):
            return view_func(request, *args, **kwargs)

    return wrapper
