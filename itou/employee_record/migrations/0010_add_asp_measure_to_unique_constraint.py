from django.db import migrations, models

from itou.asp.models import SiaeMeasure


def _fill_asp_measure(apps, schema_editor):
    EmployeeRecord = apps.get_model("employee_record", "EmployeeRecord")
    objects_to_migrate = (
        EmployeeRecord.objects.filter(asp_measure=None)
        .select_related("job_application__to_company")
        .only("job_application__to_company__kind")
    )

    batch = []
    for er in objects_to_migrate:
        er.asp_measure = SiaeMeasure.from_siae_kind(er.job_application.to_company.kind)
        batch.append(er)
    EmployeeRecord.objects.bulk_update(batch, fields=["asp_measure"])


class Migration(migrations.Migration):
    dependencies = [
        ("job_applications", "0019_rename_to_siae_jobapplication_to_company"),
        ("employee_record", "0009_employeerecord_asp_measure"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="employeerecord",
            name="unique_asp_id_approval_number",
        ),
        migrations.RunPython(_fill_asp_measure, reverse_code=migrations.RunPython.noop),
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
