from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("siae_evaluations", "0002_evaluatedadministrativecriteria_criteria_certified"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluatedsiae",
            name="final_state",
            field=models.CharField(
                blank=True,
                choices=[("ACCEPTED", "Accepted"), ("REFUSED", "Refused")],
                null=True,
                editable=False,
                verbose_name="état final après la cloture de la campagne d'évaluation",
            ),
        ),
    ]
