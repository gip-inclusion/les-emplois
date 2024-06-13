import citext
import django.contrib.postgres.fields
import django.contrib.postgres.fields.citext
import django.contrib.postgres.indexes
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Email",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "to",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=citext.CIEmailField(max_length=254),
                        size=None,
                        verbose_name="à",
                    ),
                ),
                (
                    "cc",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=citext.CIEmailField(max_length=254),
                        default=list,
                        size=None,
                        verbose_name="cc",
                    ),
                ),
                (
                    "bcc",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=citext.CIEmailField(max_length=254),
                        default=list,
                        size=None,
                        verbose_name="cci",
                    ),
                ),
                ("subject", models.TextField(verbose_name="sujet")),
                ("body_text", models.TextField(verbose_name="message")),
                ("from_email", citext.CIEmailField(max_length=254, verbose_name="de")),
                (
                    "reply_to",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=citext.CIEmailField(max_length=254),
                        default=list,
                        size=None,
                        verbose_name="répondre à",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now, verbose_name="demande d’envoi à"
                    ),
                ),
                ("esp_response", models.JSONField(null=True, verbose_name="réponse du fournisseur d’e-mail")),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    django.contrib.postgres.indexes.GinIndex(fields=["to", "cc", "bcc"], name="recipients_idx")
                ],
            },
        ),
    ]
