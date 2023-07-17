from datetime import date

from django.db import migrations


def forwards(apps, schema_editor):
    EvaluatedSiae = apps.get_model("siae_evaluations", "EvaluatedSiae")
    evaluated_siaes = EvaluatedSiae.objects.filter(
        notified_at__isnull=False,
        evaluation_campaign__evaluated_period_start_at=date(2022, 1, 1),
        sanctions=None,
    ).order_by("pk")
    evaluated_siae_pks = "\n".join(f"{e.pk}\t{e.siae_id}" for e in evaluated_siaes)
    print(f"\nReset notifications for EvaluatedSiae:\n{evaluated_siae_pks}\n")
    evaluated_siaes.update(notified_at=None)


class Migration(migrations.Migration):
    dependencies = [
        ("siae_evaluations", "0002_sanctions"),
    ]

    operations = [migrations.RunPython(forwards, elidable=True)]
