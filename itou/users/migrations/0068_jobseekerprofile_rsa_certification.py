from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0067_jobseekerprofile_creation_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobseekerprofile",
            name="rsa_certified_beneficiary",
            field=models.BooleanField(null=True, verbose_name="droits RSA ouverts (API Particulier)"),
        ),
        migrations.AddField(
            model_name="jobseekerprofile",
            name="rsa_certified_start_date",
            field=models.DateField(
                blank=True, null=True, verbose_name="droits RSA ouverts depuis le (API Particulier)"
            ),
        ),
        migrations.AddField(
            model_name="jobseekerprofile",
            name="rsa_certification_checked_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="date de vérification des droits RSA"),
        ),
        migrations.AddField(
            model_name="jobseekerprofile",
            name="rsa_last_certification_attempt_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Date à laquelle nous avons tenté pour la dernière fois de récupérer les droits RSA",
                null=True,
                verbose_name="dernière tentative de récupération des droits RSA",
            ),
        ),
    ]
