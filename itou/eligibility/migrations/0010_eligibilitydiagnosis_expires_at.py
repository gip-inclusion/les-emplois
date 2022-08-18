from django.db import migrations, models
from django.db.models import ExpressionWrapper, F, Func


def fill_expires_at(apps, _schema_editor):
    model = apps.get_model("eligibility", "EligibilityDiagnosis")
    model.objects.update(
        expires_at=ExpressionWrapper(
            F("created_at") + Func(template="interval '6 months'"),
            output_field=models.DateTimeField(),
        )
    )


class Migration(migrations.Migration):

    dependencies = [
        ("eligibility", "0009_rename_refugee_administrative_criteria"),
    ]

    operations = [
        migrations.AddField(
            model_name="eligibilitydiagnosis",
            name="expires_at",
            field=models.DateTimeField(db_index=True, blank=True, null=True, verbose_name="Date d'expiration"),
        ),
        migrations.RunPython(fill_expires_at, migrations.RunPython.noop, elidable=True),
        migrations.AlterField(
            model_name="eligibilitydiagnosis",
            name="expires_at",
            field=models.DateTimeField(db_index=True, verbose_name="Date d'expiration"),
        ),
    ]
