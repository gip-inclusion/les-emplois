from django.db import migrations


def move_data_forward(apps, schema_editor):
    """
    Set the default value for `approval_number_delivered_by`
    """
    JobApplication = apps.get_model("job_applications", "JobApplication")

    for job_application in JobApplication.objects.exclude(approval__isnull=True):

        if job_application.approval.created_by:
            job_application.approval_number_delivered_by = (
                job_application.approval.created_by
            )
            job_application.save()


class Migration(migrations.Migration):

    dependencies = [
        ("job_applications", "0022_jobapplication_approval_number_delivered_by")
    ]

    operations = [migrations.RunPython(move_data_forward, migrations.RunPython.noop)]
