import datetime

from django.db import migrations, models


def forwards(apps, schema_editor):
    Calendar = apps.get_model("siae_evaluations", "Calendar")
    Calendar.objects.update(adversarial_stage_start=datetime.date(2023, 9, 1))


class Migration(migrations.Migration):
    dependencies = [
        ("siae_evaluations", "0008_add_calendar_pk_and_content_20230602"),
    ]

    operations = [
        migrations.AddField(
            model_name="calendar",
            name="adversarial_stage_start",
            field=models.DateField(null=True, verbose_name="début de la phase contradictoire"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
        migrations.AlterField(
            model_name="calendar",
            name="adversarial_stage_start",
            field=models.DateField(verbose_name="début de la phase contradictoire"),
        ),
    ]
