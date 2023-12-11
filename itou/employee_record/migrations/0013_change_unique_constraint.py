from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employee_record", "0012_clean_data_to_change_unique_constraint"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="employeerecord",
            name="unique_asp_id_approval_number_asp_measure",
        ),
        migrations.AddConstraint(
            model_name="employeerecord",
            constraint=models.UniqueConstraint(
                fields=("asp_measure", "siret", "approval_number"), name="unique_asp_measure_siret_approval_number"
            ),
        ),
    ]
