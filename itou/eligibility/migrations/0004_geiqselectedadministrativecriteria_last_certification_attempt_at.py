from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0003_selectedadministrativecriteria_last_certification_attempt_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="geiqselectedadministrativecriteria",
            name="last_certification_attempt_at",
            field=models.DateTimeField(
                blank=True, editable=False, null=True, verbose_name="dernière tentative de certification"
            ),
        ),
    ]
