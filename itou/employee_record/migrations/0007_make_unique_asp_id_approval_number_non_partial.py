from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employee_record", "0006_remove_employeerecordupdatenotification_notification_type"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="employeerecord",
            name="unique_asp_id_approval_number",
        ),
        migrations.AddConstraint(
            model_name="employeerecord",
            constraint=models.UniqueConstraint(
                fields=("asp_id", "approval_number"), name="unique_asp_id_approval_number"
            ),
        ),
    ]
