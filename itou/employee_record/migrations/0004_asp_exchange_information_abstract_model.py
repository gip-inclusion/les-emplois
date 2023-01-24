from django.db import migrations, models

import itou.employee_record.models


class Migration(migrations.Migration):

    dependencies = [
        ("employee_record", "0003_alter_updated_at"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="employeerecordupdatenotification",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Notification de changement de la fiche salarié",
                "verbose_name_plural": "Notifications de changement de la fiche salarié",
            },
        ),
        migrations.AlterUniqueTogether(
            name="employeerecord",
            unique_together=set(),
        ),
        migrations.AddField(
            model_name="employeerecordupdatenotification",
            name="archived_json",
            field=models.JSONField(blank=True, null=True, verbose_name="Archive JSON de la fiche salarié"),
        ),
        migrations.AlterField(
            model_name="employeerecord",
            name="archived_json",
            field=models.JSONField(blank=True, null=True, verbose_name="Archive JSON de la fiche salarié"),
        ),
        migrations.AlterField(
            model_name="employeerecord",
            name="asp_batch_file",
            field=models.CharField(
                max_length=27,
                null=True,
                validators=[itou.employee_record.models.validate_asp_batch_filename],
                verbose_name="Fichier de batch ASP",
            ),
        ),
        migrations.AlterField(
            model_name="employeerecord",
            name="asp_batch_line_number",
            field=models.IntegerField(null=True, verbose_name="Ligne correspondante dans le fichier batch ASP"),
        ),
        migrations.AddConstraint(
            model_name="employeerecord",
            constraint=models.UniqueConstraint(
                condition=models.Q(("asp_batch_file__isnull", False)),
                fields=("asp_batch_file", "asp_batch_line_number"),
                name="unique_employeerecord_asp_batch_file_and_line",
            ),
        ),
        migrations.AddConstraint(
            model_name="employeerecordupdatenotification",
            constraint=models.UniqueConstraint(
                condition=models.Q(("asp_batch_file__isnull", False)),
                fields=("asp_batch_file", "asp_batch_line_number"),
                name="unique_employeerecordupdatenotification_asp_batch_file_and_line",
            ),
        ),
    ]
