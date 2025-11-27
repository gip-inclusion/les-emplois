from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="geiqselectedadministrativecriteria",
            name="certification_request_succeeded",
            field=models.BooleanField(editable=False, null=True, verbose_name="appel à l’API de certification réussi"),
        ),
        migrations.AddField(
            model_name="selectedadministrativecriteria",
            name="certification_request_succeeded",
            field=models.BooleanField(editable=False, null=True, verbose_name="appel à l’API de certification réussi"),
        ),
    ]
