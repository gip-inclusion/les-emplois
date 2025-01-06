import datetime

from django.db import migrations
from django.utils import timezone

from itou.utils.types import InclusiveDateRange


def set_certification_period_end_date(apps, editor):
    SelectedAdministrativeCriteria = apps.get_model("eligibility", "SelectedAdministrativeCriteria")
    crits = []
    changed = 0
    for crit in SelectedAdministrativeCriteria.objects.exclude(certification_period=None):
        new_end = timezone.localdate(crit.certified_at) + datetime.timedelta(days=92)
        if crit.certification_period.upper is None or abs((new_end - crit.certification_period.upper).days) >= 7:
            changed += 1
        crit.certification_period = InclusiveDateRange(crit.certification_period.lower, new_end)
        crits.append(crit)
    updated_objs = SelectedAdministrativeCriteria.objects.bulk_update(crits, fields=["certification_period"])
    print("\nChanged selected administrative criteria:")
    print(f"- {changed} end dates moved more than a week")
    print(f"- {updated_objs - changed} end dates moved <= week")


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0008_alter_eligibilitydiagnosis_expires_at_and_more"),
    ]

    operations = [
        migrations.RunPython(set_certification_period_end_date, elidable=True),
    ]
