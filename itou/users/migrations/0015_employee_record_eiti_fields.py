import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0014_alter_jobseekerprofile_birthdate__add_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobseekerprofile",
            name="activity_bonus_since",
            field=models.CharField(
                blank=True,
                choices=[
                    ("01", "Moins de 6 mois"),
                    ("02", "De 6 à 11 mois"),
                    ("03", "De 12 à 23 mois"),
                    ("04", "24 mois et plus"),
                ],
                max_length=2,
                verbose_name="allocataire de la prime d'activité depuis",
            ),
        ),
        migrations.AddField(
            model_name="jobseekerprofile",
            name="actor_met_for_business_creation",
            field=models.CharField(
                blank=True,
                help_text="Nom de l’acteur de la création d’entreprise rencontré dans le cadre d'une convention de partenariat / hors convention de partenariat",  # noqa: E501
                validators=[
                    django.core.validators.MaxLengthValidator(100),
                    django.core.validators.RegexValidator(
                        "^[a-zA-Z -]*$",
                        "Seuls les caractères alphabétiques, le tiret et l'espace sont autorisés.",  # noqa: E501
                    ),
                ],
                verbose_name="acteur rencontré",
            ),
        ),
        migrations.AddField(
            model_name="jobseekerprofile",
            name="are_allocation_since",
            field=models.CharField(
                blank=True,
                choices=[
                    ("01", "Moins de 6 mois"),
                    ("02", "De 6 à 11 mois"),
                    ("03", "De 12 à 23 mois"),
                    ("04", "24 mois et plus"),
                ],
                max_length=2,
                verbose_name="allocataire de l'ARE depuis",
            ),
        ),
        migrations.AddField(
            model_name="jobseekerprofile",
            name="cape_freelance",
            field=models.BooleanField(default=False, verbose_name="bénéficiaire CAPE"),
        ),
        migrations.AddField(
            model_name="jobseekerprofile",
            name="cesa_freelance",
            field=models.BooleanField(default=False, verbose_name="bénéficiaire CESA"),
        ),
        migrations.AddField(
            model_name="jobseekerprofile",
            name="eiti_contributions",
            field=models.CharField(
                blank=True,
                choices=[
                    ("01", "Achat/revente de marchandises"),
                    ("02", "Prestations de services commerciales et artisanales"),
                    ("03", "Autres prestations de services"),
                    ("04", "Professions libérales règlementées relevant de la Cipav"),
                    ("05", "Locations de meublés de tourisme classés"),
                    ("06", "Non déterminé (contrat établi avant 2025)"),
                ],
                max_length=2,
                verbose_name="taux de cotisation du travailleur indépendant",
            ),
        ),
        migrations.AddField(
            model_name="jobseekerprofile",
            name="mean_monthly_income_before_process",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Revenu net mensuel moyen du travailleur indépendant sur l’année précédant son entrée en parcours",  # noqa: E501
                max_digits=7,
                null=True,
                verbose_name="revenu net mensuel moyen",
            ),
        ),
    ]
