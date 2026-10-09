from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0065_user_inclusion_staff"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="email_tracking_consent",
            field=models.BooleanField(
                db_default=False,
                default=False,
                verbose_name="consentement au suivi de l’ouverture des e-mails",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="email_tracking_consent_updated_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Vide si l’utilisateur n’a jamais été interrogé",
                null=True,
                verbose_name="date du choix de suivi de l’ouverture des e-mails",
            ),
        ),
    ]
