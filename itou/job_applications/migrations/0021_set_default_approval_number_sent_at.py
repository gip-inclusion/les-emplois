from django.db import migrations


def move_data_forward(apps, schema_editor):
    """
    Set the default value for `approval_number_sent_at`
    """
    JobApplication = apps.get_model("job_applications", "JobApplication")

    for job_application in JobApplication.objects.exclude(approval__isnull=True):

        # At this time, this works because there is still only 1 approval per job_application.
        job_application.approval_number_sent_at = job_application.approval.created_at
        job_application.save()


class Migration(migrations.Migration):

    dependencies = [("job_applications", "0020_jobapplication_approval_number_sent_at")]

    operations = [migrations.RunPython(move_data_forward, migrations.RunPython.noop)]
