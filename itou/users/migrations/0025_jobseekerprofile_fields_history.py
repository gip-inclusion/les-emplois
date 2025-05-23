import django.contrib.postgres.fields
import django.core.serializers.json
import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0024_jobseekerprofile_is_stalled"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobseekerprofile",
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
                    condition='WHEN (OLD."asp_uid" IS DISTINCT FROM (NEW."asp_uid") OR OLD."fields_history" IS DISTINCT FROM (NEW."fields_history"))',  # noqa: E501
                    declare="DECLARE _rows_diff jsonb;",
                    func="\n            IF NEW.fields_history IS DISTINCT FROM OLD.fields_history THEN\n                RAISE EXCEPTION 'Modification du champ \"fields_history\" interdit';\n            END IF;\n\n            SELECT jsonb_build_object(\n                'before', jsonb_object_agg(pre.key, pre.value),\n                'after', jsonb_object_agg(post.key, post.value),\n                '_timestamp', current_timestamp\n            )\n            INTO _rows_diff\n            FROM jsonb_each(to_jsonb(OLD)) AS pre\n            CROSS JOIN jsonb_each(to_jsonb(NEW)) AS post\n            WHERE pre.key = post.key\n            AND pre.value IS DISTINCT FROM post.value\n            AND pre.key IN ('asp_uid');\n\n            NEW.fields_history = array_append(NEW.fields_history, _rows_diff);\n            RETURN NEW;\n        ",  # noqa: E501
                    hash="f74f614ed4ec0778c4e454858979da3fca08b539",
                    operation="UPDATE",
                    pgid="pgtrigger_job_seeker_profile_fields_history_61c3f",
                    table="users_jobseekerprofile",
                    when="BEFORE",
                ),
            ),
        ),
    ]
