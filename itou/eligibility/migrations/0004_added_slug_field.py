# Generated by Django 4.1.5 on 2023-01-26 13:58

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0003_criteria_with_both_annexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="geiqadministrativecriteria",
            name="slug",
            field=models.SlugField(blank=True, max_length=100, null=True, verbose_name="référence courte"),
        ),
    ]