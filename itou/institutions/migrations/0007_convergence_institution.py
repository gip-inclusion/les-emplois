from django.db import migrations, models

from itou.institutions.enums import InstitutionKind


def forwards(apps, schema_editor):
    Institution = apps.get_model("institutions", "Institution")

    Institution(
        kind=InstitutionKind.CONVERGENCE,
        name="Convergence France",
    ).save()


def backwards(apps, schema_editor):
    Institution = apps.get_model("institutions", "Institution")

    Institution.objects.filter(kind=InstitutionKind.CONVERGENCE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("institutions", "0006_alter_institution_insee_city_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="institution",
            name="kind",
            field=models.CharField(
                choices=[
                    (
                        "DDETS GEIQ",
                        "Direction départementale de l'emploi, du travail et des solidarités, division GEIQ",
                    ),
                    ("DDETS IAE", "Direction départementale de l'emploi, du travail et des solidarités, division IAE"),
                    (
                        "DDETS LOG",
                        "Direction départementale de l'emploi, du travail et des solidarités, "
                        "division logement insertion",
                    ),
                    (
                        "DREETS GEIQ",
                        "Direction régionale de l'économie, de l'emploi, du travail et des solidarités, division GEIQ",
                    ),
                    (
                        "DREETS IAE",
                        "Direction régionale de l'économie, de l'emploi, du travail et des solidarités, division IAE",
                    ),
                    ("DRIHL", "Direction régionale et interdépartementale de l'Hébergement et du Logement"),
                    ("DGEFP GEIQ", "Délégation générale à l'emploi et à la formation professionnelle, division GEIQ"),
                    ("DGEFP IAE", "Délégation générale à l'emploi et à la formation professionnelle, division IAE"),
                    ("DIHAL", "Délégation interministérielle à l'hébergement et à l'accès au logement"),
                    ("Réseau IAE", "Réseau employeur de l'insertion par l'activité économique"),
                    ("CONVERGENCE", "Convergence France"),
                    ("Autre", "Autre"),
                ],
                default="Autre",
                max_length=20,
                verbose_name="type",
            ),
        ),
        migrations.RunPython(code=forwards, reverse_code=backwards),
    ]
