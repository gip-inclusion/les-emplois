# Generated by Django 5.1.5 on 2025-02-13 21:04

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gps", "0008_alter_followupgroupmembership_last_contact_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="followupgroupmembership",
            name="started_at",
            field=models.DateTimeField(null=True, verbose_name="date de début de suivi"),
        ),
    ]
