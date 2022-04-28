from django.db import migrations


def migrate_data_forward(apps, schema_editor):  # pylint: disable=unused-argument
    AdministrativeCriteria = apps.get_model("eligibility", "AdministrativeCriteria")
    AdministrativeCriteria.objects.filter(name="Réfugié statutaire, protégé subsidiaire ou demandeur d'asile").update(
        name="Réfugié statutaire, bénéficiaire d'une protection temporaire, protégé subsidiaire ou demandeur d'asile",
        written_proof="Titre de séjour valide ou demande de renouvellement du titre de séjour. "
        "Pour les demandeurs d'asile : autorisation temporaire de travail. "
        "Pour les bénéficiaires d'une protection temporaire : autorisation provisoire de séjour.",
    )


def migrate_data_backward(apps, schema_editor):  # pylint: disable=unused-argument
    AdministrativeCriteria = apps.get_model("eligibility", "AdministrativeCriteria")
    AdministrativeCriteria.objects.filter(
        name="Réfugié statutaire, bénéficiaire d'une protection temporaire, protégé subsidiaire ou demandeur d'asile"
    ).update(
        name="Réfugié statutaire, protégé subsidiaire ou demandeur d'asile",
        written_proof="Titre de séjour valide ou demande de renouvellement du titre de séjour. "
        "Pour les demandeurs d'asile : autorisation temporaire de travail",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("eligibility", "0008_rename_rsa_administrative_criteria"),
    ]

    operations = [migrations.RunPython(migrate_data_forward, migrate_data_backward)]
