from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("socialaccount", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            # TODO(francoisfreitag): Drop IF NOT EXISTS after migration is applied on production.
            """
            CREATE INDEX
            IF NOT EXISTS
            account_emailaddress_email_upper
            ON account_emailaddress (UPPER(email) text_pattern_ops);
            """
        ),
    ]
