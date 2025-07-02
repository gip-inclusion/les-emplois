import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0023_fill_last_employer_update_at"),
    ]

    operations = [
        pgtrigger.migrations.RemoveTrigger(
            model_name="company",
            name="company_fields_history",
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="company",
            trigger=pgtrigger.compiler.Trigger(
                name="company_fields_history",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    condition='WHEN (OLD."siret" IS DISTINCT FROM (NEW."siret") OR OLD."fields_history" IS DISTINCT FROM (NEW."fields_history"))',  # noqa: E501
                    declare="DECLARE _rows_diff jsonb; current_context jsonb;",
                    func="\n            IF NEW.fields_history IS DISTINCT FROM OLD.fields_history THEN\n                RAISE EXCEPTION 'Modification du champ \"fields_history\" interdit';\n            END IF;\n\n            BEGIN\n                -- Convert empty string to NULL, this happen when set_config() was called but not for the current\n                -- transaction, this end with a 22P02/invalid_text_representation error as this is not valid JSON.\n                SELECT NULLIF(current_setting('itou.context'), '') INTO current_context;\n            EXCEPTION\n                WHEN undefined_object THEN current_context := NULL;  -- set_config() was not called, ever.\n            END;\n\n            IF current_context IS NULL THEN\n                RAISE EXCEPTION 'No context available';\n            END IF;\n\n            SELECT jsonb_build_object(\n                'before', jsonb_object_agg(pre.key, pre.value),\n                'after', jsonb_object_agg(post.key, post.value),\n                '_timestamp', current_timestamp,\n                '_context', current_context::jsonb\n            )\n            INTO _rows_diff\n            FROM jsonb_each(to_jsonb(OLD)) AS pre\n            CROSS JOIN jsonb_each(to_jsonb(NEW)) AS post\n            WHERE pre.key = post.key\n            AND pre.value IS DISTINCT FROM post.value\n            AND pre.key IN ('siret');\n\n            NEW.fields_history = array_append(NEW.fields_history, _rows_diff);\n            RETURN NEW;\n        ",  # noqa: E501
                    hash="51591a61e3b83c49a54138f666f04b153bba3846",
                    operation="UPDATE",
                    pgid="pgtrigger_company_fields_history_d170a",
                    table="companies_company",
                    when="BEFORE",
                ),
            ),
        ),
    ]
