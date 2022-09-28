from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("siae_evaluations", "0008_alter_evaluatedadministrativecriteria_review_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluatedsiae",
            name="final_reviewed_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Contrôle définitif le"),
        ),
    ]
