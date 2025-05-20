from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0012_remove_administrativecriteria_created_by_state_operation"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE eligibility_administrativecriteria DROP COLUMN IF EXISTS created_by_id",
            reverse_sql=(
                "ALTER TABLE eligibility_administrativecriteria ADD COLUMN created_by_id timestamp DEFAULT NULL"
            ),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE eligibility_geiqadministrativecriteria DROP COLUMN IF EXISTS created_by_id",
            reverse_sql=(
                "ALTER TABLE eligibility_geiqadministrativecriteria ADD COLUMN created_by_id timestamp DEFAULT NULL"
            ),
        ),
    ]
