# Generated by Django 4.2.10 on 2024-02-13 20:46

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0036_remove_user_lack_of_nir_reason_remove_user_nir"),
    ]

    operations = [
        # This migration can be merged into 0036 once run in production
        migrations.RunSQL(
            'ALTER TABLE "users_user" DROP COLUMN nir;',
            elidable=True,
        ),
        migrations.RunSQL(
            'ALTER TABLE "users_user" DROP COLUMN lack_of_nir_reason;',
            elidable=True,
        ),
    ]