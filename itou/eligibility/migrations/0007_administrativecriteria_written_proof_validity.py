from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("eligibility", "0006_rename_junior_administrative_criteria"),
    ]

    operations = [
        migrations.AddField(
            model_name="administrativecriteria",
            name="written_proof_validity",
            field=models.CharField(
                blank=True, default="", max_length=255, verbose_name="Durée de validité du justificatif"
            ),
        ),
    ]
