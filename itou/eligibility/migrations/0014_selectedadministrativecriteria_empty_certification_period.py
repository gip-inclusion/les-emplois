import datetime

from django.db import migrations

from itou.utils.types import InclusiveDateRange


def forwards(apps, schema_editor):
    SelectedAdministrativeCriteria = apps.get_model("eligibility", "SelectedAdministrativeCriteria")
    GEIQSelectedAdministrativeCriteria = apps.get_model("eligibility", "GEIQSelectedAdministrativeCriteria")
    iae = []
    for crit in SelectedAdministrativeCriteria.objects.filter(certified=True, certification_period=None):
        crit.certification_period = InclusiveDateRange(
            crit.certified_at, crit.certified_at + datetime.timedelta(days=92)
        )
        iae.append(crit)
    SelectedAdministrativeCriteria.objects.bulk_update(iae, fields=["certification_period"])
    geiq = []
    for crit in GEIQSelectedAdministrativeCriteria.objects.filter(certified=True, certification_period=None):
        crit.certification_period = InclusiveDateRange(
            crit.certified_at, crit.certified_at + datetime.timedelta(days=92)
        )
        geiq.append(crit)
    GEIQSelectedAdministrativeCriteria.objects.bulk_update(iae, fields=["certification_period"])
    print()
    print(f"Fixed IAE={len(iae)} GEIQ={len(geiq)} selected administrative criteria certification periods.")


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0013_remove_administrative_criteria_created_by_database_operation"),
    ]

    operations = [migrations.RunPython(forwards, elidable=True)]
