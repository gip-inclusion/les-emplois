# Generated by Django 5.1.7 on 2025-03-28 14:27

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gps", "0020_delete_francetravailcontact"),
    ]

    operations = [
        migrations.AddField(
            model_name="followupgroupmembership",
            name="is_referent_certified",
            field=models.BooleanField(db_default=False, verbose_name="référent certifié"),
        ),
    ]
