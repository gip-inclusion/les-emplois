import django.contrib.postgres.fields
import django.core.serializers.json
import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0042_jobseekerprofile_ase_exit_and_more"),
    ]

    operations = [
        pgtrigger.migrations.RemoveTrigger(
            model_name="jobseekerprofile",
            name="job_seeker_profile_fields_history",
        ),
        migrations.AddField(
            model_name="user",
            name="fields_history",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.JSONField(encoder=django.core.serializers.json.DjangoJSONEncoder),
                db_default=[],
                default=list,
                size=None,
                verbose_name="historique des champs modifiés sur le modèle",
            ),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="jobseekerprofile",
            trigger=pgtrigger.compiler.Trigger(
                name="job_seeker_profile_fields_history",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    condition='WHEN (OLD."asp_uid" IS DISTINCT FROM (NEW."asp_uid") OR OLD."birthdate" IS DISTINCT FROM (NEW."birthdate") OR OLD."birth_place_id" IS DISTINCT FROM (NEW."birth_place_id") OR OLD."birth_country_id" IS DISTINCT FROM (NEW."birth_country_id") OR OLD."is_not_stalled_anymore" IS DISTINCT FROM (NEW."is_not_stalled_anymore") OR OLD."pole_emploi_id" IS DISTINCT FROM (NEW."pole_emploi_id") OR OLD."fields_history" IS DISTINCT FROM (NEW."fields_history"))',  # noqa: E501
                    declare="DECLARE _rows_diff jsonb; current_context jsonb;",
                    func="\n            IF NEW.fields_history IS DISTINCT FROM OLD.fields_history THEN\n                RAISE EXCEPTION 'Modification du champ \"fields_history\" interdit';\n            END IF;\n\n            BEGIN\n                -- Convert empty string to NULL, this happen when set_config() was called but not for the current\n                -- transaction, this end with a 22P02/invalid_text_representation error as this is not valid JSON.\n                SELECT NULLIF(current_setting('itou.context'), '') INTO current_context;\n            EXCEPTION\n                WHEN undefined_object THEN current_context := NULL;  -- set_config() was not called, ever.\n            END;\n\n            IF current_context IS NULL THEN\n                RAISE EXCEPTION 'No context available';\n            END IF;\n\n            SELECT jsonb_build_object(\n                'before', jsonb_object_agg(pre.key, pre.value),\n                'after', jsonb_object_agg(post.key, post.value),\n                '_timestamp', current_timestamp,\n                '_context', current_context::jsonb\n            )\n            INTO _rows_diff\n            FROM jsonb_each(to_jsonb(OLD)) AS pre\n            CROSS JOIN jsonb_each(to_jsonb(NEW)) AS post\n            WHERE pre.key = post.key\n            AND pre.value IS DISTINCT FROM post.value\n            AND pre.key IN ('asp_uid','birthdate','birth_place_id','birth_country_id','is_not_stalled_anymore','pole_emploi_id');\n\n            NEW.fields_history = array_append(NEW.fields_history, _rows_diff);\n            RETURN NEW;\n        ",  # noqa: E501
                    hash="c113aad8933a288925fddf521c02aaf48d3276ad",
                    operation="UPDATE",
                    pgid="pgtrigger_job_seeker_profile_fields_history_61c3f",
                    table="users_jobseekerprofile",
                    when="BEFORE",
                ),
            ),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="user",
            trigger=pgtrigger.compiler.Trigger(
                name="user_fields_history",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    condition='WHEN (OLD."first_name" IS DISTINCT FROM (NEW."first_name") OR OLD."last_name" IS DISTINCT FROM (NEW."last_name") OR OLD."title" IS DISTINCT FROM (NEW."title") OR OLD."email" IS DISTINCT FROM (NEW."email") OR OLD."phone" IS DISTINCT FROM (NEW."phone") OR OLD."address_line_1" IS DISTINCT FROM (NEW."address_line_1") OR OLD."address_line_2" IS DISTINCT FROM (NEW."address_line_2") OR OLD."post_code" IS DISTINCT FROM (NEW."post_code") OR OLD."city" IS DISTINCT FROM (NEW."city") OR OLD."fields_history" IS DISTINCT FROM (NEW."fields_history"))',  # noqa: E501
                    declare="DECLARE _rows_diff jsonb; current_context jsonb;",
                    func="\n            IF NEW.fields_history IS DISTINCT FROM OLD.fields_history THEN\n                RAISE EXCEPTION 'Modification du champ \"fields_history\" interdit';\n            END IF;\n\n            BEGIN\n                -- Convert empty string to NULL, this happen when set_config() was called but not for the current\n                -- transaction, this end with a 22P02/invalid_text_representation error as this is not valid JSON.\n                SELECT NULLIF(current_setting('itou.context'), '') INTO current_context;\n            EXCEPTION\n                WHEN undefined_object THEN current_context := NULL;  -- set_config() was not called, ever.\n            END;\n\n            IF current_context IS NULL THEN\n                RAISE EXCEPTION 'No context available';\n            END IF;\n\n            SELECT jsonb_build_object(\n                'before', jsonb_object_agg(pre.key, pre.value),\n                'after', jsonb_object_agg(post.key, post.value),\n                '_timestamp', current_timestamp,\n                '_context', current_context::jsonb\n            )\n            INTO _rows_diff\n            FROM jsonb_each(to_jsonb(OLD)) AS pre\n            CROSS JOIN jsonb_each(to_jsonb(NEW)) AS post\n            WHERE pre.key = post.key\n            AND pre.value IS DISTINCT FROM post.value\n            AND pre.key IN ('first_name','last_name','title','email','phone','address_line_1','address_line_2','post_code','city');\n\n            NEW.fields_history = array_append(NEW.fields_history, _rows_diff);\n            RETURN NEW;\n        ",  # noqa: E501
                    hash="69cfbea3a07611b2bd1384bc027b4d3a6c4a63f4",
                    operation="UPDATE",
                    pgid="pgtrigger_user_fields_history_57f2b",
                    table="users_user",
                    when="BEFORE",
                ),
            ),
        ),
    ]
