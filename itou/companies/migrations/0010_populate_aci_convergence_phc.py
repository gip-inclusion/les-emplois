from django.conf import settings
from django.db import migrations


def forwards(apps, editor):
    SiaeACIConvergencePHC = apps.get_model("companies", "SiaeACIConvergencePHC")
    SiaeACIConvergencePHC.objects.bulk_create(
        SiaeACIConvergencePHC(siret=siret) for siret in settings.ACI_CONVERGENCE_SIRET_WHITELIST
    )


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0009_siaeaciconvergencephc"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True)]
