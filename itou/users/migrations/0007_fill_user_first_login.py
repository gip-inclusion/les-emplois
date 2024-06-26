# Generated by Django 5.0.6 on 2024-05-30 07:50

import time

from django.db import migrations
from django.db.models import F


def _fill_user_first_login(apps, schema_editor):
    User = apps.get_model("users", "User")
    users = User.objects.filter(first_login=None).exclude(last_login=None)

    count = 0
    start = time.perf_counter()
    while batch_users := users[:10000]:
        count += User.objects.filter(pk__in=batch_users.values_list("pk", flat=True)).update(
            first_login=F("date_joined")
        )
        print(f"{count} users migrated in {time.perf_counter() - start:.2f} sec")


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0006_user_first_login"),
    ]

    operations = [
        migrations.RunPython(_fill_user_first_login, migrations.RunPython.noop, elidable=True),
    ]
