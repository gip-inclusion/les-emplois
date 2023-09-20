from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employee_record", "0008_unarchive_recent_employee_record"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeerecord",
            name="asp_measure",
            field=models.CharField(
                choices=[
                    ("AI_DC", "Droit Commun - Association Intermédiaire"),
                    ("ACI_DC", "Droit Commun - Atelier et Chantier d'Insertion"),
                    ("EI_DC", "Droit Commun -  Entreprise d'Insertion"),
                    ("ETTI_DC", "Droit Commun - Entreprise de Travail Temporaire d'Insertion"),
                    ("EITI_DC", "Droit Commun - Entreprise d'Insertion par le Travail Indépendant"),
                    ("FDI_DC", "Droit Commun -  Fonds Départemental pour l'Insertion"),
                    ("EI_MP", "Milieu Pénitentiaire - Entreprise d'Insertion"),
                    ("ACI_MP", "Milieu Pénitentiaire - Atelier et Chantier d'Insertion"),
                ],
                null=True,
                verbose_name="mesure ASP de la SIAE",
            ),
        ),
    ]
