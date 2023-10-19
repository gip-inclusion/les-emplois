from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0002_siae_geocoded_label_siae_geocoding_updated_at"),
    ]

    operations = [
        migrations.RunSQL(
            """
            UPDATE siaes_siae SET updated_at = created_at WHERE updated_at IS NULL;
            UPDATE siaes_siaeconvention SET updated_at = created_at WHERE updated_at IS NULL;
            UPDATE siaes_siaefinancialannex SET updated_at = created_at WHERE updated_at IS NULL;
            UPDATE siaes_siaejobdescription SET updated_at = created_at WHERE updated_at IS NULL;
            UPDATE siaes_siaemembership SET updated_at = created_at WHERE updated_at IS NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        ),
        migrations.AlterField(
            model_name="siae",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="date de modification"),
        ),
        migrations.AlterField(
            model_name="siaeconvention",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="date de modification"),
        ),
        migrations.AlterField(
            model_name="siaefinancialannex",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="date de modification"),
        ),
        migrations.AlterField(
            model_name="siaejobdescription",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, db_index=True, verbose_name="date de modification"),
        ),
        migrations.AlterField(
            model_name="siaemembership",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="date de modification"),
        ),
    ]
