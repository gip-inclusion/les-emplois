import datetime

from django.db import migrations


def forwards(apps, editor):
    EvaluationCampaign = apps.get_model("siae_evaluations", "EvaluationCampaign")
    EvaluatedJobApplication = apps.get_model("siae_evaluations", "EvaluatedJobApplication")
    EvaluatedSiae = apps.get_model("siae_evaluations", "EvaluatedSiae")

    campaigns_2021 = EvaluationCampaign.objects.filter(evaluated_period_end_at__lte=datetime.date(2021, 12, 31))
    print()
    print("Deleted objects:")
    print(EvaluatedJobApplication.objects.filter(evaluated_siae__evaluation_campaign__in=campaigns_2021).delete())
    print(EvaluatedSiae.objects.filter(evaluation_campaign__in=campaigns_2021).delete())
    print(campaigns_2021.delete())


class Migration(migrations.Migration):
    dependencies = [
        ("siae_evaluations", "0002_alter_evaluatedadministrativecriteria_administrative_criteria_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, elidable=True),
    ]
