from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0012_add_prolongation_request"),
    ]

    operations = [
        migrations.AddField(
            model_name="prolongationrequest",
            name="reminder_sent_at",
            field=models.DateTimeField(editable=False, null=True, verbose_name="rappel envoyé le"),
        ),
    ]
