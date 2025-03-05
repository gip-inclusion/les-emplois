from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employee_record", "0004_employeerecordtransitionlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeerecordtransitionlog",
            name="recovered",
            field=models.BooleanField(
                default=False, editable=False, verbose_name="récupéré rétroactivement avec un script"
            ),
        ),
    ]
