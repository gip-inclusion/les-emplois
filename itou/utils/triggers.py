import functools
import operator
from typing import Any

from django.db import models
from pgtrigger import Condition, core


class FieldsHistory(core.Trigger):
    when: core.When = core.Before
    operation: core.Operation = core.Update
    declare: list[tuple[str, str]] | None = [("_rows_diff", "jsonb")]
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
        fields = [model._meta.get_field(field).name for field in self.fields + [self.HISTORY_FIELD_NAME]]
        return functools.reduce(
            operator.or_,
            [core.Q(**{f"old__{field}__df": core.F(f"new__{field}")}) for field in fields],
        )

    def get_func(self, model):
        sql_fields = [f"'{field}'" for field in self.fields]
        return f"""
            IF NEW.{self.HISTORY_FIELD_NAME} IS DISTINCT FROM OLD.{self.HISTORY_FIELD_NAME} THEN
                RAISE EXCEPTION 'Modification du champ "{self.HISTORY_FIELD_NAME}" interdit';
            END IF;

            SELECT jsonb_build_object(
                'before', jsonb_object_agg(pre.key, pre.value),
                'after', jsonb_object_agg(post.key, post.value),
                '_timestamp', current_timestamp
            )
            INTO _rows_diff
            FROM jsonb_each(to_jsonb(OLD)) AS pre
            CROSS JOIN jsonb_each(to_jsonb(NEW)) AS post
            WHERE pre.key = post.key
            AND pre.value IS DISTINCT FROM post.value
            AND pre.key IN ({','.join(sql_fields)});

            NEW.{self.HISTORY_FIELD_NAME} = array_append(NEW.{self.HISTORY_FIELD_NAME}, _rows_diff);
            RETURN NEW;
        """
