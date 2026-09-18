from itertools import batched

from django.db import migrations


def prefix_deactivated_usernames(apps, schema_editor):
    """
    Rewrite the username of users deactivated before prefixing the username with `old_<pk>_<sub>`.
    """
    BATCH_SIZE = 10_000
    User = apps.get_model("users", "User")
    users = User.objects.filter(is_active=False)
    total = users.count()
    nb_updated = 0
    print("")
    print("Total deactivated users:", total)
    for user_batch in batched(users.iterator(chunk_size=BATCH_SIZE), BATCH_SIZE):
        for user in user_batch:
            user.username = f"old_{user.pk}_{user.username.removeprefix('old_').removesuffix('_old')}"
        nb_updated += User.objects.bulk_update(user_batch, ["username"])
        print(f"Updated {nb_updated}/{total} deactivated users")



class Migration(migrations.Migration):
    dependencies = [
        ("users", "0062_remove_jobseekerprofile_ft_gps_id"),
    ]

    operations = [
        migrations.RunPython(prefix_deactivated_usernames, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
