"""Data migration: clear eligibility_diagnosis, geiq_eligibility_diagnosis, and approval
on all non-accepted JobApplications."""

from django.db import migrations


def clear_non_accepted_fk_fields(apps, schema_editor):
    JobApplication = apps.get_model("job_applications", "JobApplication")
    qs = JobApplication.objects.exclude(state="accepted").exclude(
        eligibility_diagnosis=None,
        geiq_eligibility_diagnosis=None,
        approval=None,
    )
    updated = qs.update(
        eligibility_diagnosis=None,
        geiq_eligibility_diagnosis=None,
        approval=None,
    )
    if updated:
        print(f"  Cleared FK fields on {updated} non-accepted job applications.")


class Migration(migrations.Migration):
    dependencies = [
        ("job_applications", "0005_alter_jobapplication_hiring_start_at"),
    ]

    operations = [
        migrations.RunPython(clear_non_accepted_fk_fields, migrations.RunPython.noop, elidable=True),
    ]
