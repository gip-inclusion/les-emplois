import sys
import time

from django.db import migrations
from django.db.models import F, Q


def create_or_verify_emailaddresses(apps, schema_editor):
    print(file=sys.stderr)

    EmailAddress = apps.get_model("account", "EmailAddress")
    User = apps.get_model("users", "User")
    batch_size = 5_000
    batch = 0
    batches = User.objects.count() // batch_size + 1
    while True:
        batch_start = batch * batch_size
        batch_end = (batch + 1) * batch_size
        batch += 1
        print(f"    Batch {batch:3d} of approximately {batches}.", file=sys.stderr)

        emailaddresses = []
        users = User.objects.exclude(
            Q(email=None) | Q(email=""),
        ).filter(
            pk__gte=batch_start,
            pk__lt=batch_end,
        )
        if not users and not User.objects.filter(pk__gte=batch_end).exists():
            break
        for user in users:
            emailaddresses.append(
                EmailAddress(
                    email=user.email,
                    user_id=user.pk,
                    primary=True,
                    verified=bool(user.last_login),
                )
            )
        EmailAddress.objects.bulk_create(emailaddresses, ignore_conflicts=True)

        time.sleep(10)

    EmailAddress.objects.exclude(
        user__last_login=None,
    ).filter(
        user__email=F("email")
    ).update(verified=True)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("users", "0024_alter_jobseekerprofile_birth_country_and_more"),
    ]

    operations = [
        migrations.RunPython(
            create_or_verify_emailaddresses,
            migrations.RunPython.noop,
            elidable=True,
        ),
    ]
