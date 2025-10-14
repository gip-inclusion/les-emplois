from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0002_update_certification_periods_from_certified"),
    ]

    operations = [
        migrations.AddField(
            model_name="selectedadministrativecriteria",
            name="last_certification_attempt_at",
            field=models.DateTimeField(
                blank=True, editable=False, null=True, verbose_name="dernière tentative de certification"
            ),
        ),
    ]
