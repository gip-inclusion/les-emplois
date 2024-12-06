from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0007_geiqselectedadministrativecriteria_certification_period_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="eligibilitydiagnosis",
            name="expires_at",
            field=models.DateField(
                db_index=True,
                verbose_name="date d'expiration",
                help_text="Diagnosic expiré à compter de ce jour",
            ),
        ),
        migrations.AlterField(
            model_name="geiqeligibilitydiagnosis",
            name="expires_at",
            field=models.DateField(
                db_index=True,
                verbose_name="date d'expiration",
                help_text="Diagnosic expiré à compter de ce jour",
            ),
        ),
    ]
