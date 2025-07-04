# Generated by Django 5.2.3 on 2025-06-27 08:51

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("job_applications", "0018_alter_jobapplication_options"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.AlterField(
                    model_name="jobapplication",
                    name="hiring_without_approval",
                    field=models.BooleanField(
                        db_default=False,
                        verbose_name="l'entreprise choisit de ne pas obtenir un PASS\xa0IAE à l'embauche",
                    ),
                ),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name="jobapplication",
                    name="hiring_without_approval",
                ),
            ],
        )
    ]
