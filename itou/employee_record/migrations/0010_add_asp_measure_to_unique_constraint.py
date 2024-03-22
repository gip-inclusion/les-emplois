from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("job_applications", "0001_initial"),
        ("employee_record", "0009_employeerecord_asp_measure"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="employeerecord",
            name="unique_asp_id_approval_number",
        ),
        migrations.AlterField(
            model_name="employeerecord",
            name="asp_measure",
            field=models.CharField(
                choices=[
                    ("ACI_DC", "Droit Commun - Atelier et Chantier d'Insertion"),
                    ("AI_DC", "Droit Commun - Association Intermédiaire"),
                    ("EI_DC", "Droit Commun -  Entreprise d'Insertion"),
                    ("EITI_DC", "Droit Commun - Entreprise d'Insertion par le Travail Indépendant"),
                    ("ETTI_DC", "Droit Commun - Entreprise de Travail Temporaire d'Insertion"),
                    ("ACI_MP", "Milieu Pénitentiaire - Atelier et Chantier d'Insertion"),
                    ("EI_MP", "Milieu Pénitentiaire - Entreprise d'Insertion"),
                    ("FDI_DC", "Droit Commun -  Fonds Départemental pour l'Insertion"),
                ],
                verbose_name="mesure ASP de la SIAE",
            ),
        ),
        migrations.AddConstraint(
            model_name="employeerecord",
            constraint=models.UniqueConstraint(
                fields=("asp_id", "approval_number", "asp_measure"), name="unique_asp_id_approval_number_asp_measure"
            ),
        ),
    ]
