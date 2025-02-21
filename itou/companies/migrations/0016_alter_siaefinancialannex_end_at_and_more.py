from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0015_fix_financial_annexes_dates"),
    ]

    operations = [
        migrations.AlterField(
            model_name="siaefinancialannex",
            name="end_at",
            field=models.DateField(verbose_name="date de fin d'effet"),
        ),
        migrations.AlterField(
            model_name="siaefinancialannex",
            name="start_at",
            field=models.DateField(verbose_name="date de début d'effet"),
        ),
    ]
