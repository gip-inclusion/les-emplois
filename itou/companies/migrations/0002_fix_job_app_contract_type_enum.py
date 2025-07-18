# Generated by Django 5.0.6 on 2024-05-24 04:27

from django.db import migrations


def _fix_contract_type_enum(apps, schema_editor):
    JobDescription = apps.get_model("companies", "JobDescription")
    JobDescription.objects.filter(contract_type="FED_TERM_I_PHC").update(contract_type="FIXED_TERM_I_PHC")


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(_fix_contract_type_enum, migrations.RunPython.noop, elidable=True),
    ]
