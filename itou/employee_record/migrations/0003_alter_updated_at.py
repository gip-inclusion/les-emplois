from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employee_record", "0002_add_notification_update_trigger"),
    ]

    operations = [
        migrations.AlterField(
            model_name="employeerecord",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="Date de modification"),
        ),
        migrations.AlterField(
            model_name="employeerecordupdatenotification",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="Date de modification"),
        ),
    ]
