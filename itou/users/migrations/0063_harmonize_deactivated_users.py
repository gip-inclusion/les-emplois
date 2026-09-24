from itertools import batched

from django.db import migrations


def prefix_deactivated_usernames(apps, schema_editor):
    """
    Rewrite the username of users deactivated before prefixing the username with `old_<pk>_<sub>`.
    """
    BATCH_SIZE = 10_000
    nb_updated = 0
    User = apps.get_model("users", "User")
    users = User.objects.filter(is_active=False).exclude(kind="itou_staff")
    for user_batch in batched(users.iterator(chunk_size=BATCH_SIZE), BATCH_SIZE):
        users_to_update = []
        for user in user_batch:
            if user.username.startswith(f"old_{user.pk}_"):  # Already rewritten
                continue
            user.username = f"old_{user.pk}_{user.username.removeprefix('old_').removesuffix('_old')}"
            users_to_update.append(user)
        nb_updated += User.objects.bulk_update(users_to_update, ["username"])
    print("")
    print(f"Updated {nb_updated} deactivated users")


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0062_remove_jobseekerprofile_ft_gps_id"),
    ]

    operations = [
        migrations.RunPython(prefix_deactivated_usernames, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
