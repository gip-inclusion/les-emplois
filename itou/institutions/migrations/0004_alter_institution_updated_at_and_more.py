from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("institutions", "0003_alter_institution_kind"),
    ]

    operations = [
        migrations.RunSQL(
            """
            UPDATE institutions_institution SET updated_at = created_at WHERE updated_at IS NULL;
            UPDATE institutions_institutionmembership SET updated_at = created_at WHERE updated_at IS NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        ),
        migrations.AlterField(
            model_name="institution",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="date de modification"),
        ),
        migrations.AlterField(
            model_name="institutionmembership",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="date de modification"),
        ),
    ]
