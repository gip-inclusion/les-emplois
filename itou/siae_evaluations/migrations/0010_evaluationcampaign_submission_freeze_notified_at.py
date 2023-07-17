from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("siae_evaluations", "0009_calendar_adversarial_stage_start"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluationcampaign",
            name="submission_freeze_notified_at",
            field=models.DateTimeField(
                editable=False,
                help_text="Date de dernière notification des DDETS après blocage des soumissions SIAE",
                null=True,
                verbose_name="notification des DDETS après blocage des soumissions SIAE",
            ),
        ),
    ]
