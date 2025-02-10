from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            """
            CREATE INDEX
            account_emailaddress_email_upper
            ON account_emailaddress (UPPER(email) text_pattern_ops);
            """
        ),
    ]
