from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("employee_record", "0005_stop_using_notification_type_field"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="employeerecordupdatenotification",
            name="notification_type",
        ),
    ]
