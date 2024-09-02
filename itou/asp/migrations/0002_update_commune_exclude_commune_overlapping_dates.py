# Generated by Django 5.0.8 on 2024-09-05 19:49

import django.contrib.postgres.constraints
import django.contrib.postgres.fields.ranges
from django.db import migrations

import itou.utils.models


class Migration(migrations.Migration):
    dependencies = [
        ("asp", "0001_initial"),
        ("cities", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="commune",
            name="exclude_commune_overlapping_dates",
        ),
        migrations.AddConstraint(
            model_name="commune",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                expressions=(
                    ("code", "="),
                    (
                        itou.utils.models.DateRange(
                            "start_date",
                            "end_date",
                            django.contrib.postgres.fields.ranges.RangeBoundary(
                                inclusive_lower=True, inclusive_upper=True
                            ),
                        ),
                        "&&",
                    ),
                ),
                name="exclude_commune_overlapping_dates",
                violation_error_message="La période chevauche une autre période existante pour ce même code INSEE.",
            ),
        ),
    ]