from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0005_fill_approvals_eligibility_diagnoses"),
    ]

    operations = [
        migrations.RunSQL(
            """UPDATE approvals_prolongation SET updated_at = created_at WHERE updated_at IS NULL;""",
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        ),
        migrations.AlterField(
            model_name="prolongation",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="Date de modification"),
        ),
        migrations.AlterField(
            model_name="suspension",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True, verbose_name="Date de modification"),
        ),
    ]
