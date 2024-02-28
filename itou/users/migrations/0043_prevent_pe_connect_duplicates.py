import time

from django.db import IntegrityError, migrations, transaction


def fill_username_from_allauth(apps, schema_editor):
    SocialAccount = apps.get_model("socialaccount", "SocialAccount")
    total = updated = 0
    for account in SocialAccount.objects.select_related("user").filter(
        provider="peamu",  # all social accounts come from peamu, but just in case.
    ):
        total += 1
        if updated % 1000 == 0:
            # Go easy on the DB.
            time.sleep(1)
        if account.user.username != account.uid:
            account.user.username = account.uid
            try:
                with transaction.atomic():
                    account.user.save(update_fields=["username"])
            except IntegrityError:
                pass
            else:
                updated += 1
    print()
    print(f"Set username to PE Connect sub for {updated} users out of {total}")


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0042_drop_user_asp_uid_in_db"),
        ("socialaccount", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(fill_username_from_allauth, migrations.RunPython.noop, elidable=True),
    ]
