from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("siae_evaluations", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluatedadministrativecriteria",
            name="criteria_certified",
            field=models.BooleanField(db_default=False, verbose_name="certifié par un système de l’État"),
        ),
    ]
