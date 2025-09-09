from django.db import migrations, models

from itou.siae_evaluations.models import EvaluatedSiae


def populate_final_state(apps, schema_editor):
    evaluated_siaes = list(
        EvaluatedSiae.objects.filter(evaluation_campaign__ended_at__isnull=False)
        .prefetch_related("evaluated_job_applications__evaluated_administrative_criteria")
        .select_for_update(of=("self",), no_key=True)
    )

    for evaluated_siae in evaluated_siaes:
        evaluated_siae.final_state = evaluated_siae.state

    updated = EvaluatedSiae.objects.bulk_update(evaluated_siaes, ["final_state"])
    print(f"updated {updated} EvaluatedSiae")


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
        migrations.RunPython(code=populate_final_state, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
