import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="KV",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.BinaryField(verbose_name="clé")),
                ("value", models.BinaryField(verbose_name="valeur")),
                (
                    "is_result",
                    models.BooleanField(default=False, verbose_name="résultat"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Schedule",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("queue", models.CharField(default="huey")),
                ("data", models.BinaryField()),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now,
                        verbose_name="date de création",
                    ),
                ),
                (
                    "timestamp",
                    models.DateTimeField(blank=True, null=True, verbose_name="exécution le"),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.RenameIndex(
            model_name="task",
            new_name="tasks_task_created_at_idx",
            old_name="created_at_idx",
        ),
        migrations.RenameIndex(
            model_name="task",
            new_name="tasks_priority_not_null_idx",
            old_name="priority_not_null_idx",
        ),
        migrations.AddField(
            model_name="task",
            name="queue",
            field=models.CharField(default="huey"),
        ),
        migrations.AddConstraint(
            model_name="kv",
            constraint=models.UniqueConstraint(models.F("key"), name="tasks_kv_key_uniq"),
        ),
        migrations.AddIndex(
            model_name="schedule",
            index=models.Index(models.F("created_at"), name="tasks_schedule_created_at_idx"),
        ),
        migrations.AddIndex(
            model_name="schedule",
            index=models.Index(
                models.F("timestamp"),
                condition=models.Q(("timestamp__isnull", False)),
                name="tasks_timestamp_not_null_idx",
            ),
        ),
    ]
