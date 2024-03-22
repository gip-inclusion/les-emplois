import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("job_applications", "0001_initial"),
        ("employee_record", "0013_change_unique_constraint"),
    ]

    operations = [
        migrations.AlterField(
            model_name="employeerecord",
            name="job_application",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="employee_record",
                to="job_applications.jobapplication",
                verbose_name="candidature / embauche",
            ),
        ),
    ]
