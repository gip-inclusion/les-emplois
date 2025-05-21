import datetime

from django.db import migrations

from itou.utils.types import InclusiveDateRange


def forwards(apps, schema_editor):
    GEIQSelectedAdministrativeCriteria = apps.get_model("eligibility", "GEIQSelectedAdministrativeCriteria")
    geiq = []
    for crit in GEIQSelectedAdministrativeCriteria.objects.filter(certified=True, certification_period=None):
        crit.certification_period = InclusiveDateRange(
            crit.certified_at, crit.certified_at + datetime.timedelta(days=92)
        )
        geiq.append(crit)
    # Previous migration used the `iae` variable here instead of `geiq`.
    # Thankfully, no rows were touched in production.
    # https://github.com/gip-inclusion/les-emplois/pull/6173#discussion_r2099704697
    GEIQSelectedAdministrativeCriteria.objects.bulk_update(geiq, fields=["certification_period"])
    print()
    print(f"Fixed GEIQ={len(geiq)} selected administrative criteria certification periods.")


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0014_selectedadministrativecriteria_empty_certification_period"),
    ]

    operations = [migrations.RunPython(forwards, elidable=True)]
