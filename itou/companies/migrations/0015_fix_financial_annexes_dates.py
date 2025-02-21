import datetime

from django.db import migrations
from django.db.models import F


def forwards(apps, editor):
    SiaeFinancialAnnex = apps.get_model("companies", "SiaeFinancialAnnex")
    # The datetime stored in the database are dates cast to datetimes (time set to midnight),
    # then interpreted as in the current timezone (Europe/Paris) and stored in UTC.
    #
    # The result are silly validity period, such as:
    # start_at      | 2022-12-31 23:00:00+00
    # end_at        | 2023-12-30 23:00:00+00
    #
    # By adding two hours, we compensate for the timezone offset to UTC with DST,
    # so that the truncation to date (next migration) keeps the correct date.
    SiaeFinancialAnnex.objects.update(
        start_at=F("start_at") + datetime.timedelta(hours=2),
        end_at=F("end_at") + datetime.timedelta(hours=2),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0014_company_fields_history_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, elidable=True),
    ]
