import django.contrib.postgres.constraints
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0010_approval_update_employee_record_watched_data_updated_at"),
        ("companies", "0013_siaeconvention_convention_siret_signature_regex"),
        ("eligibility", "0007_rename_zrr"),
        ("files", "0001_initial"),
        ("job_applications", "0010_hard_remove_jobapplication_prehiring_guidance_days"),
        ("prescribers", "0004_remove_prescriberorganization_is_gps_authorized"),
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
