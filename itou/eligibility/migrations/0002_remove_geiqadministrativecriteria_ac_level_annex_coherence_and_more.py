# Generated by Django 5.0.6 on 2024-06-17 08:34

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="geiqadministrativecriteria",
            name="ac_level_annex_coherence",
        ),
        migrations.AddConstraint(
            model_name="geiqadministrativecriteria",
            constraint=models.CheckConstraint(
                check=models.Q(
                    models.Q(("annex__in", ("0", "1")), ("level__isnull", True)),
                    models.Q(("annex__in", ("2", "1+2")), ("level__in", ("1", "2")), ("level__isnull", False)),
                    _connector="OR",
                ),
                name="administrativecriteria_level_annex_consistency",
                violation_error_message="Incohérence entre l'annexe du critère administratif et son niveau",
            ),
        ),
    ]