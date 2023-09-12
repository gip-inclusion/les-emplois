from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0014_migrate_triggers"),
    ]

    operations = [
        migrations.RunSQL(
            "UPDATE approvals_suspension SET updated_at = created_at WHERE updated_at IS NULL;",
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        ),
        migrations.AlterField(
            model_name="suspension",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="date de modification"),
        ),
    ]
