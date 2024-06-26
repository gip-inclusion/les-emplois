# Generated by Django 5.0.6 on 2024-06-28 13:13

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gps", "0003_fill_groups_created_in_bulk"),
    ]

    operations = [
        migrations.AlterField(
            model_name="followupgroup",
            name="created_at",
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
        ),
        migrations.AlterField(
            model_name="followupgroupmembership",
            name="created_at",
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
        ),
    ]
