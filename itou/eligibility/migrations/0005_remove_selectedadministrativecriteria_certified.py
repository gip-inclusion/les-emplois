from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0004_geiqselectedadministrativecriteria_last_certification_attempt_at"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(
                    model_name="SelectedAdministrativeCriteria",
                    name="certified",
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(
                    model_name="GEIQSelectedAdministrativeCriteria",
                    name="certified",
                ),
            ],
        ),
    ]
