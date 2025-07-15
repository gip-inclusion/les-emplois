import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("asp", "0008_update_commune_lomme"),
        ("prescribers", "0015_drop_is_head_office_for_real"),
        ("users", "0034_add_context_to_triggers"),
    ]

    operations = [
        pgtrigger.migrations.RemoveTrigger(
            model_name="jobseekerprofile",
            name="job_seeker_profile_fields_history",
        ),
        migrations.RemoveIndex(
            model_name="jobseekerprofile",
            name="users_jobseeker_stalled_idx",
        ),
        migrations.AddField(
            model_name="jobseekerprofile",
            name="is_not_stalled_anymore",
            field=models.BooleanField(blank=True, null=True, db_default=None),
        ),
        migrations.AddIndex(
            model_name="jobseekerprofile",
            index=models.Index(
                condition=models.Q(("is_stalled", True)),
                fields=["is_stalled", "is_not_stalled_anymore"],
                name="users_jobseeker_stalled_idx",
            ),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="jobseekerprofile",
            trigger=pgtrigger.compiler.Trigger(
                name="job_seeker_profile_fields_history",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    condition='WHEN (OLD."asp_uid" IS DISTINCT FROM (NEW."asp_uid") OR OLD."is_not_stalled_anymore" IS DISTINCT FROM (NEW."is_not_stalled_anymore") OR OLD."fields_history" IS DISTINCT FROM (NEW."fields_history"))',  # noqa: E501
                    declare="DECLARE _rows_diff jsonb; current_context jsonb;",
                    func="\n            IF NEW.fields_history IS DISTINCT FROM OLD.fields_history THEN\n                RAISE EXCEPTION 'Modification du champ \"fields_history\" interdit';\n            END IF;\n\n            BEGIN\n                -- Convert empty string to NULL, this happen when set_config() was called but not for the current\n                -- transaction, this end with a 22P02/invalid_text_representation error as this is not valid JSON.\n                SELECT NULLIF(current_setting('itou.context'), '') INTO current_context;\n            EXCEPTION\n                WHEN undefined_object THEN current_context := NULL;  -- set_config() was not called, ever.\n            END;\n\n            IF current_context IS NULL THEN\n                RAISE EXCEPTION 'No context available';\n            END IF;\n\n            SELECT jsonb_build_object(\n                'before', jsonb_object_agg(pre.key, pre.value),\n                'after', jsonb_object_agg(post.key, post.value),\n                '_timestamp', current_timestamp,\n                '_context', current_context::jsonb\n            )\n            INTO _rows_diff\n            FROM jsonb_each(to_jsonb(OLD)) AS pre\n            CROSS JOIN jsonb_each(to_jsonb(NEW)) AS post\n            WHERE pre.key = post.key\n            AND pre.value IS DISTINCT FROM post.value\n            AND pre.key IN ('asp_uid','is_not_stalled_anymore');\n\n            NEW.fields_history = array_append(NEW.fields_history, _rows_diff);\n            RETURN NEW;\n        ",  # noqa: E501
                    hash="e411154d0ab7a1682baffff6796b192fe6f962c7",
                    operation="UPDATE",
                    pgid="pgtrigger_job_seeker_profile_fields_history_61c3f",
                    table="users_jobseekerprofile",
                    when="BEFORE",
                ),
            ),
        ),
    ]
