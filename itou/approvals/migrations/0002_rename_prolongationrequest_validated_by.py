from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameField(model_name="prolongationrequest", old_name="validated_by", new_name="assigned_to"),
    ]
