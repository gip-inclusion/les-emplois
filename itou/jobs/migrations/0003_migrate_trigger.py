import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0002_create_full_text_trigger"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TRIGGER IF EXISTS jobs_appellation_full_text_trigger ON jobs_appellation;",
            elidable=True,
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="appellation",
            trigger=pgtrigger.compiler.Trigger(
                name="jobs_appellation_full_text_trigger",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    execute='tsvector_update_trigger("full_text", "public.french_unaccent", "name", "rome_id")',
                    func="",
                    hash="b06f63ec0910f1c669dca88dcfa3f3ec69c23af5",
                    operation='INSERT OR UPDATE OF "name", "rome_id"',
                    pgid="pgtrigger_jobs_appellation_full_text_trigger_de796",
                    table="jobs_appellation",
                    when="BEFORE",
                ),
            ),
        ),
    ]
