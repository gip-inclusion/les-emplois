import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0001_initial"),
        ("companies", "0007_rename_siae_company"),
    ]

    replaces = [("approvals", "0002_approval_origin")]

    operations = [
        migrations.AddField(
            model_name="suspension",
            name="siae",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="approvals_suspended",
                to="companies.company",
                verbose_name="SIAE",
            ),
        ),
        migrations.AddField(
            model_name="prolongationrequest",
            name="declared_by_siae",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="companies.company",
                verbose_name="SIAE du déclarant",
            ),
        ),
        migrations.AddField(
            model_name="prolongation",
            name="declared_by_siae",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="companies.company",
                verbose_name="SIAE du déclarant",
            ),
        ),
    ]
