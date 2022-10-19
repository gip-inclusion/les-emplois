from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("siae_evaluations", "0010_finalize_evaluation_campaign_2021"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluatedsiae",
            name="notification_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("DELAY", "Non respect des délais"),
                    ("INVALID_PROOF", "Pièce justificative incorrecte"),
                    ("MISSING_PROOF", "Pièce justificative manquante"),
                    ("OTHER", "Autre"),
                ],
                max_length=255,
                null=True,
                verbose_name="raison principale",
            ),
        ),
        migrations.AddField(
            model_name="evaluatedsiae",
            name="notification_text",
            field=models.TextField(blank=True, null=True, verbose_name="commentaire"),
        ),
        migrations.AddField(
            model_name="evaluatedsiae",
            name="notified_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="notifiée le"),
        ),
    ]
