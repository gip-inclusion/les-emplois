from itertools import batched

from django.db import migrations


def harmonize_deactivated_users(apps, schema_editor):
    """
    Align users deactivated before the username was prefixed with `old_<pk>_<sub>` and the email was removed.
    """
    BATCH_SIZE = 10_000
    nb_updated = 0
    User = apps.get_model("users", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")

    users = User.objects.filter(is_active=False).exclude(kind="itou_staff")
    for user_batch in batched(users.iterator(chunk_size=BATCH_SIZE), BATCH_SIZE):
        users_to_update = []
        for user in user_batch:
            if user.username.startswith(f"old_{user.pk}_"):  # Already rewritten
                continue
            user.username = f"old_{user.pk}_{user.username.removeprefix('old_').removesuffix('_old')}"
            user.email = None
            users_to_update.append(user)
        nb_updated += User.objects.bulk_update(users_to_update, ["username", "email"])
    print("")
    print(f"Updated {nb_updated} deactivated users")

    nb_deleted, _ = EmailAddress.objects.filter(user__is_active=False).exclude(user__kind="itou_staff").delete()
    print(f"Deleted {nb_deleted} email addresses of deactivated users")


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0062_remove_jobseekerprofile_ft_gps_id"),
    ]

    operations = [
        migrations.RunPython(harmonize_deactivated_users, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
