# Generated by Django 4.2.9 on 2024-02-08 09:19

import django.db.models.deletion
import django.db.models.manager
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DisabledNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("disabled_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="NotificationRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("notification_class", models.CharField(unique=True)),
                ("name", models.CharField()),
                ("category", models.CharField()),
                ("can_be_disabled", models.BooleanField()),
                ("is_obsolete", models.BooleanField(db_index=True, default=False)),
            ],
            options={"base_manager_name": "include_obsolete", "ordering": ["category", "name"]},
            managers=[
                ("objects", django.db.models.manager.Manager()),
                ("include_obsolete", django.db.models.manager.Manager()),
            ],
        ),
        migrations.CreateModel(
            name="NotificationSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("structure_pk", models.PositiveIntegerField(null=True)),
                (
                    "disabled_notifications",
                    models.ManyToManyField(
                        related_name="+",
                        through="communications.DisabledNotification",
                        to="communications.notificationrecord",
                    ),
                ),
                (
                    "structure_type",
                    models.ForeignKey(
                        null=True, on_delete=django.db.models.deletion.CASCADE, to="contenttypes.contenttype"
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_settings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "base_manager_name": "objects",
            },
        ),
        migrations.AddField(
            model_name="disablednotification",
            name="notification_record",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, to="communications.notificationrecord"
            ),
        ),
        migrations.AddField(
            model_name="disablednotification",
            name="settings",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, to="communications.notificationsettings"
            ),
        ),
        migrations.AddConstraint(
            model_name="notificationrecord",
            constraint=models.CheckConstraint(
                check=models.Q(("category", ""), ("name", ""), _connector="OR", _negated=True),
                name="notificationrecord_category_and_name_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="notificationsettings",
            constraint=models.UniqueConstraint(
                models.F("user"),
                condition=models.Q(("structure_pk__isnull", True)),
                name="unique_settings_per_individual_user",
            ),
        ),
        migrations.AddConstraint(
            model_name="notificationsettings",
            constraint=models.UniqueConstraint(
                models.F("user"),
                models.F("structure_type"),
                models.F("structure_pk"),
                condition=models.Q(("structure_pk__isnull", False)),
                name="unique_settings_per_organizational_user",
            ),
        ),
        migrations.AddConstraint(
            model_name="disablednotification",
            constraint=models.UniqueConstraint(
                models.F("notification_record"), models.F("settings"), name="unique_notificationrecord_per_settings"
            ),
        ),
    ]