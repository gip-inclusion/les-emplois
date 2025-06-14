# Generated by Django 5.1.9 on 2025-06-02 08:25

from django.db import migrations
from django.utils import timezone

from itou.utils.admin import add_support_remark_to_obj


# assumptions for this migration in june 2025:
# - all prolongations declared by job seeker have a declared_by_siae, no need to handle this case
# - 2 prolongations declared by job seeker have a declared_by_siae without any active membership
# - we expect to update 51 prolongations declared by job seeker


def forward(apps, schema_editor):
    Prolongation = apps.get_model("approvals", "Prolongation")
    CompanyMembership = apps.get_model("companies", "CompanyMembership")

    # do not select_for_update, due to nullable new_declared_by
    prolongations_declared_by_jobseeker = Prolongation.objects.filter(declared_by__kind="job_seeker").select_related(
        "declared_by_siae", "declared_by"
    )

    now = timezone.now().strftime("%Y-%m-%d")

    for prolongation in prolongations_declared_by_jobseeker:
        declared_by = prolongation.declared_by
        declared_by_siae = prolongation.declared_by_siae

        # migration fails on prolongation.declared_by_siae.memberships
        # use this queryset instead
        membership = (
            CompanyMembership.objects.filter(company=declared_by_siae, is_active=True, user__is_active=True)
            .select_related("user")
            .first()
        )
        new_declared_by = membership.user if membership else None

        support_message = [
            f"{now}",
            "reprise de données automatique",
            f"prolongation déclarée par le candidat {declared_by.id}",
        ]

        if new_declared_by:
            support_message.append(f"remplacement par {new_declared_by.id}")
            prolongation.declared_by = new_declared_by
        else:
            support_message.append(f"aucun membre trouvé pour la SIAE {declared_by_siae.id}, suppression du déclarant")
            prolongation.declared_by = None

        add_support_remark_to_obj(prolongation, ", ".join(support_message))
        prolongation.save(update_fields=["declared_by"])


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0011_allow_more_status_for_employee_record_notifications"),
    ]

    operations = [
        migrations.RunPython(code=forward, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
