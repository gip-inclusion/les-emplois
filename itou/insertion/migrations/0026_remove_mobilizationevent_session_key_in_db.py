from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0013_siaeconvention_convention_siret_signature_regex"),
        ("insertion", "0025_remove_mobilizationevent_session_key_and_more"),
        ("prescribers", "0004_remove_prescriberorganization_is_gps_authorized"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL("ALTER TABLE insertion_mobilizationevent DROP COLUMN session_key;")
            ],
            state_operations=[],
        ),
    ]
