import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import itou.employee_record.models


class Migration(migrations.Migration):
    dependencies = [
        ("employee_record", "0003_alter_employeerecord_status_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EmployeeRecordTransitionLog",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("transition", models.CharField(db_index=True, max_length=255, verbose_name="transition")),
                ("from_state", models.CharField(db_index=True, max_length=255, verbose_name="from state")),
                ("to_state", models.CharField(db_index=True, max_length=255, verbose_name="to state")),
                (
                    "timestamp",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now, verbose_name="performed at"
                    ),
                ),
                (
                    "asp_processing_code",
                    models.CharField(max_length=4, null=True, verbose_name="code de traitement ASP"),
                ),
                (
                    "asp_processing_label",
                    models.CharField(max_length=200, null=True, verbose_name="libellé de traitement ASP"),
                ),
                (
                    "asp_batch_file",
                    models.CharField(
                        max_length=27,
                        null=True,
                        validators=[itou.employee_record.models.validate_asp_batch_filename],
                        verbose_name="fichier de batch ASP",
                    ),
                ),
                (
                    "asp_batch_line_number",
                    models.IntegerField(null=True, verbose_name="ligne correspondante dans le fichier batch ASP"),
                ),
                (
                    "archived_json",
                    models.JSONField(blank=True, null=True, verbose_name="archive JSON de la fiche salarié"),
                ),
                (
                    "employee_record",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="logs",
                        to="employee_record.employeerecord",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "log des transitions de la fiche salarié",
                "verbose_name_plural": "log des transitions des fiches salarié",
                "ordering": ["-timestamp"],
                "abstract": False,
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("asp_batch_file__isnull", False)),
                        fields=("asp_batch_file", "asp_batch_line_number"),
                        name="unique_employeerecordtransitionlog_asp_batch_file_and_line",
                    )
                ],
            },
        ),
    ]
