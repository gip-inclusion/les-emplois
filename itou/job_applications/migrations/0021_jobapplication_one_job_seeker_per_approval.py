import django.contrib.postgres.constraints
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0013_alter_approval_options"),
        ("companies", "0023_fill_last_employer_update_at"),
        ("eligibility", "0015_geiqselectedadministrativecriteria_empty_certification_period"),
        ("files", "0009_alter_file_id"),
        ("job_applications", "0020_alter_and_sync_sender_kind"),
        ("prescribers", "0015_drop_is_head_office_for_real"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="jobapplication",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                condition=models.Q(("approval_id", None), _negated=True),
                expressions=[("approval_id", "="), ("job_seeker_id", "<>")],
                name="one_job_seeker_per_approval",
                violation_error_message="Le PASS IAE est déjà utilisé par un autre candidat.",
            ),
        ),
    ]
