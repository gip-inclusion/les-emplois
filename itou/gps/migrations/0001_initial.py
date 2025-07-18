# Generated by Django 5.2.4 on 2025-07-16 14:29

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FollowUpGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="date de modification")),
                (
                    "beneficiary",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="follow_up_group",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="bénéficiaire",
                    ),
                ),
                (
                    "created_in_bulk",
                    models.BooleanField(db_index=True, default=False, verbose_name="créé massivement"),
                ),
            ],
            options={
                "verbose_name": "groupe de suivi",
                "verbose_name_plural": "groupes de suivi",
            },
        ),
        migrations.CreateModel(
            name="FollowUpGroupMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True, verbose_name="actif")),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
                ),
                ("ended_at", models.DateField(blank=True, null=True, verbose_name="date de fin de suivi")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="date de modification")),
                (
                    "creator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="created_follow_up_groups",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="créateur",
                    ),
                ),
                (
                    "follow_up_group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="gps.followupgroup",
                        verbose_name="groupe de suivi",
                    ),
                ),
                (
                    "member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="follow_up_groups",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="membre du groupe de suivi",
                    ),
                ),
                (
                    "created_in_bulk",
                    models.BooleanField(db_index=True, default=False, verbose_name="créé massivement"),
                ),
                (
                    "last_contact_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de dernier contact"),
                ),
                ("started_at", models.DateField(verbose_name="date de début de suivi")),
                ("reason", models.TextField(blank=True, verbose_name="motif de suivi")),
                (
                    "can_view_personal_information",
                    models.BooleanField(default=False, verbose_name="accès aux données du bénéficiaire"),
                ),
                (
                    "end_reason",
                    models.CharField(
                        blank=True,
                        choices=[("AUTOMATIC", "automatique"), ("MANUAL", "manuel")],
                        max_length=30,
                        null=True,
                        verbose_name="motif de fin",
                    ),
                ),
                ("is_referent_certified", models.BooleanField(db_default=False, verbose_name="référent certifié")),
            ],
            options={"verbose_name": "relation"},
        ),
        migrations.AddField(
            model_name="followupgroup",
            name="members",
            field=models.ManyToManyField(
                related_name="follow_up_groups_member",
                through="gps.FollowUpGroupMembership",
                through_fields=("follow_up_group", "member"),
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="followupgroupmembership",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("end_reason", None), ("ended_at", None)),
                    models.Q(("end_reason__isnull", False), ("ended_at__isnull", False)),
                    _connector="OR",
                ),
                name="end_coherence",
                violation_error_message="Incohérence du champ motif de fin",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="followupgroupmembership",
            unique_together={("follow_up_group", "member")},
        ),
    ]
