import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = True  # Explicitly declared default value

    dependencies = [
        ("emails", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailAddress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(db_index=True, max_length=254, verbose_name="adresse e-mail")),
                ("verified", models.BooleanField(default=False, verbose_name="vérifiée")),
                ("primary", models.BooleanField(default=False, verbose_name="principale")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_addresses",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "adresse e-mail",
                "verbose_name_plural": "adresses e-mail",
            },
        ),
        migrations.CreateModel(
            name="EmailConfirmation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created", models.DateTimeField(default=django.utils.timezone.now, verbose_name="créé")),
                ("sent", models.DateTimeField(null=True, verbose_name="envoyé")),
                ("key", models.CharField(max_length=64, unique=True, verbose_name="clé")),
                (
                    "email_address",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="emails.emailaddress",
                        verbose_name="adresse e-mail",
                    ),
                ),
            ],
            options={
                "verbose_name": "confirmation par e-mail",
                "verbose_name_plural": "confirmations par e-mail",
            },
        ),
        migrations.RunSQL(
            """
            INSERT INTO emails_emailaddress ("id", "user_id", "email", "verified")
            SELECT "id", "user_id", "email", "verified"
            FROM account_emailaddress;
            """
        ),
        migrations.RunSQL(
            """
            INSERT INTO emails_emailconfirmation ("id", "email_address_id", "created", "sent", "key")
            SELECT "id", "email_address_id", "created", "sent", "key"
            FROM account_emailconfirmation;
            """
        ),
        # TODO(calum): make email addresses globally unique
        #   (in allauth they are unique to user-email and email-verified)
        # TODO(calum): The instances now migrated,
        #   we can now remove the django-allauth models and change the name of below UniqueConstraint
    ]
