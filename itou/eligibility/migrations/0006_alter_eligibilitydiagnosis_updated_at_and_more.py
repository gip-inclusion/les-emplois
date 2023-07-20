from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0005_updated_dual_annexes"),
    ]

    operations = [
        migrations.RunSQL(
            """
            UPDATE eligibility_eligibilitydiagnosis SET updated_at = created_at WHERE updated_at IS NULL;
            UPDATE eligibility_geiqeligibilitydiagnosis SET updated_at = created_at WHERE updated_at IS NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        ),
        migrations.AlterField(
            model_name="eligibilitydiagnosis",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, db_index=True, verbose_name="date de modification"),
        ),
        migrations.AlterField(
            model_name="geiqeligibilitydiagnosis",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, db_index=True, verbose_name="date de modification"),
        ),
    ]
