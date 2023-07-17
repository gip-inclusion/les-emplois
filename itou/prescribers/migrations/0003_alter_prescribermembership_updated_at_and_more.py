from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("prescribers", "0002_prescriberorganization_geocoded_label_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            """
            UPDATE prescribers_prescribermembership SET updated_at = created_at WHERE updated_at IS NULL;
            UPDATE prescribers_prescriberorganization SET updated_at = created_at WHERE updated_at IS NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        ),
        migrations.AlterField(
            model_name="prescribermembership",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="Date de modification"),
        ),
        migrations.AlterField(
            model_name="prescriberorganization",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="Date de modification"),
        ),
    ]
