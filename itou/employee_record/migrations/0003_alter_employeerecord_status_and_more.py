import django_xworkflows.models
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("employee_record", "0002_fix_archived_json_as_string"),
    ]

    operations = [
        migrations.AlterField(
            model_name="employeerecord",
            name="status",
            field=django_xworkflows.models.StateField(
                max_length=10,
                verbose_name="statut",
                workflow=django_xworkflows.models._SerializedWorkflow(
                    initial_state="NEW",
                    name="EmployeeRecordWorkflow",
                    states=["NEW", "READY", "SENT", "REJECTED", "PROCESSED", "DISABLED", "ARCHIVED"],
                ),
            ),
        ),
        migrations.AlterField(
            model_name="employeerecordupdatenotification",
            name="status",
            field=django_xworkflows.models.StateField(
                max_length=10,
                verbose_name="statut",
                workflow=django_xworkflows.models._SerializedWorkflow(
                    initial_state="NEW",
                    name="EmployeeRecordUpdateNotificationWorkflow",
                    states=["NEW", "SENT", "PROCESSED", "REJECTED"],
                ),
            ),
        ),
    ]
