import django.contrib.postgres.fields
import django.core.serializers.json
import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0013_company_automatic_geocoding_update"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
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
            model_name="company",
            trigger=pgtrigger.compiler.Trigger(
                name="company_fields_history",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    condition='WHEN (OLD."siret" IS DISTINCT FROM (NEW."siret") OR OLD."fields_history" IS DISTINCT FROM (NEW."fields_history"))',  # noqa: E501
                    declare="DECLARE _rows_diff jsonb;",
                    func="\n            IF NEW.fields_history IS DISTINCT FROM OLD.fields_history THEN\n                RAISE EXCEPTION 'Modification du champ \"fields_history\" interdit';\n            END IF;\n\n            SELECT jsonb_build_object(\n                'before', jsonb_object_agg(pre.key, pre.value),\n                'after', jsonb_object_agg(post.key, post.value),\n                '_timestamp', current_timestamp\n            )\n            INTO _rows_diff\n            FROM jsonb_each(to_jsonb(OLD)) AS pre\n            CROSS JOIN jsonb_each(to_jsonb(NEW)) AS post\n            WHERE pre.key = post.key\n            AND pre.value IS DISTINCT FROM post.value\n            AND pre.key IN ('siret');\n\n            NEW.fields_history = array_append(NEW.fields_history, _rows_diff);\n            RETURN NEW;\n        ",  # noqa: E501
                    hash="50ab920b043e229804465fbb337c060400de01fc",
                    operation="UPDATE",
                    pgid="pgtrigger_company_fields_history_d170a",
                    table="companies_company",
                    when="BEFORE",
                ),
            ),
        ),
    ]
