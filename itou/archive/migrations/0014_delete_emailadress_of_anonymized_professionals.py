from django.conf import settings
from django.db import migrations

from itou.utils.enums import ItouEnvironment


def delete_emailaddress_of_anonymized_professionals(apps, schema_editor):
    if settings.ITOU_ENVIRONMENT != ItouEnvironment.PROD:
        return

    EmailAddress = apps.get_model("account", "EmailAddress")
    EmailAddress.objects.filter(user__email__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("archive", "0013_remove_evaluated_jobseekers"),
    ]

    operations = [
        migrations.RunPython(
            code=delete_emailaddress_of_anonymized_professionals, reverse_code=migrations.RunPython.noop, elidable=True
        ),
    ]
