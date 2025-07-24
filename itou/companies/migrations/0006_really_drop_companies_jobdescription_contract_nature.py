from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0005_remove_jobdescription_contract_nature"),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE companies_jobdescription DROP COLUMN IF EXISTS contract_nature;",
            migrations.RunSQL.noop,
            elidable=True,
        ),
    ]
