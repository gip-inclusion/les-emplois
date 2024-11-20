from django.db import migrations
from django.db.models import OuterRef, Subquery


def create_email_addresses_for_users(apps, schema_editor):
    User = apps.get_model("users", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")

    # Get all those values of User.email where there is no corresponding EmailAddresses instance
    users_missing_addresses = (
        User.objects.prefetch_related("emailaddress_set")
        .annotate(email_exists=Subquery(EmailAddress.objects.filter(email=OuterRef("email")).values("id")[:1]))
        .filter(email_exists__isnull=True)
        .values("id", "email")
    )

    EmailAddress.objects.bulk_create(
        EmailAddress(user_id=x["id"], email=x["email"], primary=True, verified=False) for x in users_missing_addresses
    )


class Migration(migrations.Migration):
    """
    This migration was created at a time when not all User email addresses had an associated EmailAddress.
    It ensures that EmailAddress instances are created where they are not existing.
    Of course this means that the migration can be squashed later.
    """

    dependencies = [
        ("users", "0014_alter_jobseekerprofile_birthdate__add_index"),
    ]

    operations = [
        migrations.RunPython(
            create_email_addresses_for_users,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
