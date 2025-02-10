from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("emails", "0002_remove_django_allauth"),
    ]

    operations = [
        migrations.AddField(
            model_name="emailconfirmation",
            name="used",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Pour des raisons de sécurité, un lien de confirmation ne peut être utilisé qu'une seule fois."
                ),
                verbose_name="utilisée",
            ),
        ),
    ]
