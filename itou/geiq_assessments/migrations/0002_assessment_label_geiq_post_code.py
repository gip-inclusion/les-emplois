# Generated by Django 5.2.2 on 2025-06-16 08:13

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("geiq_assessments", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessment",
            name="label_geiq_post_code",
            field=models.CharField(db_default="", verbose_name="code postal du GEIQ principal dans label"),
        ),
    ]
