from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0006_remove_abstractselectedadministrativecriteria_certified"),
    ]

    # This migration is NOT a no-op: it triggers a post-migration
    # signal that will update criteria in the database from JSON
    # reference files (see `eligibility/apps.py`).
    operations = []
