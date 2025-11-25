from django.db import migrations, models
from django.utils import timezone

import itou.utils.validators


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0008_contract"),
    ]

    operations = [
        migrations.CreateModel(
            name="SiaeACIConvergencePHC",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "siret",
                    models.CharField(
                        editable=False,
                        max_length=14,
                        unique=True,
                        validators=[itou.utils.validators.validate_siret],
                        verbose_name="SIRET",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(default=timezone.now, verbose_name="date de création"),
                ),
            ],
            options={
                "verbose_name": "ACI Convergence / PHC",
                "verbose_name_plural": "ACI Convergence / PHC",
            },
        ),
        migrations.AddConstraint(
            model_name="siaeaciconvergencephc",
            constraint=models.CheckConstraint(
                condition=models.Q(("siret__regex", "\\A[0-9]{14}\\Z")), name="aci_cvg_phc_siret"
            ),
        ),
    ]
