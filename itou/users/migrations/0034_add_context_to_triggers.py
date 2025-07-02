import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0033_alter_user_kind"),
    ]

    operations = [
        pgtrigger.migrations.RemoveTrigger(
            model_name="jobseekerprofile",
            name="job_seeker_profile_fields_history",
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="jobseekerprofile",
            trigger=pgtrigger.compiler.Trigger(
                name="job_seeker_profile_fields_history",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    condition='WHEN (OLD."asp_uid" IS DISTINCT FROM (NEW."asp_uid") OR OLD."fields_history" IS DISTINCT FROM (NEW."fields_history"))',  # noqa: E501
                    declare="DECLARE _rows_diff jsonb; current_context jsonb;",
                    func="\n            IF NEW.fields_history IS DISTINCT FROM OLD.fields_history THEN\n                RAISE EXCEPTION 'Modification du champ \"fields_history\" interdit';\n            END IF;\n\n            BEGIN\n                -- Convert empty string to NULL, this happen when set_config() was called but not for the current\n                -- transaction, this end with a 22P02/invalid_text_representation error as this is not valid JSON.\n                SELECT NULLIF(current_setting('itou.context'), '') INTO current_context;\n            EXCEPTION\n                WHEN undefined_object THEN current_context := NULL;  -- set_config() was not called, ever.\n            END;\n\n            IF current_context IS NULL THEN\n                RAISE EXCEPTION 'No context available';\n            END IF;\n\n            SELECT jsonb_build_object(\n                'before', jsonb_object_agg(pre.key, pre.value),\n                'after', jsonb_object_agg(post.key, post.value),\n                '_timestamp', current_timestamp,\n                '_context', current_context::jsonb\n            )\n            INTO _rows_diff\n            FROM jsonb_each(to_jsonb(OLD)) AS pre\n            CROSS JOIN jsonb_each(to_jsonb(NEW)) AS post\n            WHERE pre.key = post.key\n            AND pre.value IS DISTINCT FROM post.value\n            AND pre.key IN ('asp_uid');\n\n            NEW.fields_history = array_append(NEW.fields_history, _rows_diff);\n            RETURN NEW;\n        ",  # noqa: E501
                    hash="a8789460bc838020712eb1057c952d3ef32e9b0a",
                    operation="UPDATE",
                    pgid="pgtrigger_job_seeker_profile_fields_history_61c3f",
                    table="users_jobseekerprofile",
                    when="BEFORE",
                ),
            ),
        ),
    ]
