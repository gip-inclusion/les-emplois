from itertools import batched

from django.db import migrations


def harmonize_deactivated_users(apps, schema_editor):
    """
    Align users deactivated before the username was prefixed with `old_<pk>_<sub>` and the email was removed.
    """
    BATCH_SIZE = 10_000
    User = apps.get_model("users", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")

    users = User.objects.filter(is_active=False)
    total = users.count()
    nb_updated = 0
    print("")
    print("Total deactivated users:", total)
    for user_batch in batched(users.iterator(chunk_size=BATCH_SIZE), BATCH_SIZE):
        for user in user_batch:
            user.username = f"old_{user.pk}_{user.username.removeprefix('old_').removesuffix('_old')}"
            user.email = None
        nb_updated += User.objects.bulk_update(user_batch, ["username", "email"])
        print(f"Updated {nb_updated}/{total} deactivated users")

    nb_deleted, _ = EmailAddress.objects.filter(user__in=users).delete()
    print(f"Deleted {nb_deleted} email addresses of deactivated users")


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0062_remove_jobseekerprofile_ft_gps_id"),
    ]

    operations = [
        migrations.RunPython(harmonize_deactivated_users, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
