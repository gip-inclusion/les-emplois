# Generated by Django 5.1.8 on 2025-04-08 14:20

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("prescribers", "0011_remove_prescriberorganization_is_authorized_faked"),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "prescribers_prescriberorganization" DROP COLUMN "is_authorized" CASCADE;',
            reverse_sql="""
                ALTER TABLE "prescribers_prescriberorganization" ADD COLUMN is_authorized BOOLEAN;
                UPDATE "prescribers_prescriberorganization" SET is_authorized = (authorization_status='VALIDATED');
            """,
            elidable=True,
        ),
    ]
