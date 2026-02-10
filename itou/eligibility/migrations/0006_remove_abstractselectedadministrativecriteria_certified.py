from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0005_remove_selectedadministrativecriteria_certified"),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE eligibility_selectedadministrativecriteria DROP COLUMN IF EXISTS certified;",
            elidable=True,
        ),
        migrations.RunSQL(
            "ALTER TABLE eligibility_geiqselectedadministrativecriteria DROP COLUMN IF EXISTS certified;",
            elidable=True,
        ),
    ]
