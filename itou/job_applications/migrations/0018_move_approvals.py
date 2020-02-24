from django.db import migrations


def move_data_forward(apps, schema_editor):
    """
    Business has changed.
    One Approval can be used in multiple accepted JobApplication.

    Move some fields:
    - `Approval.pk` to `JobApplication.approval`
    - `Approval.number_sent_by_email` to `JobApplication.approval_number_sent_by_email`
    """
    Approval = apps.get_model("approvals", "Approval")
    JobApplication = apps.get_model("job_applications", "JobApplication")

    for approval in Approval.objects.all():

        if not approval.job_application:
            print("-" * 80)
            print(
                f"FIXME: the job application linked to this approval has been deleted: {approval.pk}"
            )
            continue

        job_application = JobApplication.objects.get(pk=approval.job_application.pk)
        job_application.approval = approval
        job_application.approval_number_sent_by_email = approval.number_sent_by_email
        job_application.approval_delivery_mode = "manual"
        job_application.save()


class Migration(migrations.Migration):

    dependencies = [
        ("approvals", "0006_auto_20200130_1948"),
        ("job_applications", "0017_jobapplication_approval"),
    ]

    operations = [migrations.RunPython(move_data_forward, migrations.RunPython.noop)]
