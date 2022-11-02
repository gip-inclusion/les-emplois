from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("siae_evaluations", "0011_evaluatedsiae_notification"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluatedsiae",
            name="reminder_sent_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="rappel envoyé le"),
        ),
    ]
