# Generated by Django 5.0.7 on 2024-08-06 09:04

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("geiq", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="implementationassessment",
            name="reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="reviewed_geiq_assessment_set",
                to=settings.AUTH_USER_MODEL,
                verbose_name="contrôlé par",
            ),
        ),
        migrations.AlterField(
            model_name="implementationassessment",
            name="submitted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="submitted_geiq_assessment_set",
                to=settings.AUTH_USER_MODEL,
                verbose_name="transmis par",
            ),
        ),
    ]
