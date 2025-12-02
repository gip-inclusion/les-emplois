from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0002_update_certification_periods_from_certified"),
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
