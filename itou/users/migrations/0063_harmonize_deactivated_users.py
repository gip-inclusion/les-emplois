from itertools import batched

from django.contrib.auth.hashers import make_password
from django.db import migrations


def harmonize_deactivated_users(apps, schema_editor):
    """
    Align users deactivated before the admin deactivation matched the archive deactivation.
    """
    BATCH_SIZE = 10_000
    User = apps.get_model("users", "User")
    JobSeekerAssignment = apps.get_model("users", "JobSeekerAssignment")
    EmailAddress = apps.get_model("account", "EmailAddress")
    ItouTOTPDevice = apps.get_model("otp", "ItouTOTPDevice")
    ItouStaticDevice = apps.get_model("otp", "ItouStaticDevice")

    nb_updated = 0
    users = User.objects.filter(is_active=False).exclude(kind="itou_staff")
    for user_batch in batched(users.iterator(chunk_size=BATCH_SIZE), BATCH_SIZE):
        users_to_update = []
        for user in user_batch:
            if user.username.startswith(f"old_{user.pk}_"):  # Already harmonized
                continue
            user.username = f"old_{user.pk}_{user.username.removeprefix('old_').removesuffix('_old')}"
            user.email = None
            user.password = make_password(None)
            user.phone = ""
            user.address_line_1 = ""
            user.address_line_2 = ""
            user.post_code = ""
            user.city = ""
            user.coords = None
            user.insee_city = None
            users_to_update.append(user)
        nb_updated += User.objects.bulk_update(
            users_to_update,
            [
                "username",
                "email",
                "password",
                "phone",
                "address_line_1",
                "address_line_2",
                "post_code",
                "city",
                "coords",
                "insee_city",
            ],
        )
    print("")
    print(f"Updated {nb_updated} deactivated users")

    nb_deleted, _ = EmailAddress.objects.filter(user__is_active=False).exclude(user__kind="itou_staff").delete()
    print(f"Deleted {nb_deleted} email addresses of deactivated users")

    for model in [ItouTOTPDevice, ItouStaticDevice]:
        nb_deleted, _ = model.objects.filter(user__is_active=False).exclude(user__kind="itou_staff").delete()
        print(f"Deleted {nb_deleted} {model.__name__} of deactivated users")

    nb_deleted, _ = JobSeekerAssignment.objects.filter(
        professional__is_active=False,
        prescriber_organization__isnull=True,
        company__isnull=True,
    ).delete()
    print(f"Deleted {nb_deleted} assignments without organization or company of deactivated professionals")


class Migration(migrations.Migration):
    dependencies = [
        ("otp", "0004_remove_itoutotpdevice_unique_name_per_user_and_more"),
        ("users", "0062_remove_jobseekerprofile_ft_gps_id"),
    ]

    operations = [
        migrations.RunPython(harmonize_deactivated_users, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
