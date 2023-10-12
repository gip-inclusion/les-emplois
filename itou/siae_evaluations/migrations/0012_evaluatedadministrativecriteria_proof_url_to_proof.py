import re

from django.conf import settings
from django.db import migrations, models, transaction


def forwards(apps, schema_editor):
    print()
    EvaluatedAdministrativeCriteria = apps.get_model("siae_evaluations", "EvaluatedAdministrativeCriteria")
    EvaluatedAdministrativeCriteria = apps.get_model("siae_evaluations", "EvaluatedAdministrativeCriteria")
    File = apps.get_model("files", "File")
    key_re = re.compile(
        rf"^{settings.AWS_S3_ENDPOINT_URL}{settings.AWS_STORAGE_BUCKET_NAME}/(?P<key>evaluations/.*\.[pP][dD][fF])$"
    )
    criterias = []
    with transaction.atomic():
        for criteria in EvaluatedAdministrativeCriteria.objects.filter(proof=None).exclude(proof_url=""):
            if match := key_re.match(criteria.proof_url):
                criteria.proof, _created = File.objects.get_or_create(key=match.group("key"))
                criterias.append(criteria)
            else:
                print(f"Could not migrate proof “{criteria.proof_url}”.")
        count = EvaluatedAdministrativeCriteria.objects.bulk_update(criterias, fields=["proof"])
    print(f"Migrated {count} evaluated administrative criteria")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("siae_evaluations", "0011_evaluatedadministrativecriteria_proof"),
        ("files", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
        migrations.AlterField(
            model_name="evaluatedadministrativecriteria",
            name="proof_url",
            field=models.URLField(blank=True, null=True, max_length=500, verbose_name="lien vers le justificatif"),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(model_name="evaluatedadministrativecriteria", name="proof_url"),
            ],
        ),
    ]
