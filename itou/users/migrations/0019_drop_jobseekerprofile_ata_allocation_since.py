from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0018_remove_jobseekerprofile_ata_allocation_since"),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "users_jobseekerprofile" DROP COLUMN IF EXISTS "ata_allocation_since" CASCADE',
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        ),
    ]
