# Generated by Django 5.0.6 on 2024-06-27 12:53
import datetime
import logging
import time

from django.conf import settings
from django.db import migrations
from django.db.models import Q


logger = logging.getLogger(__name__)


def _bulk_created_lookup():
    created_at_as_dt = datetime.datetime.combine(
        settings.GPS_GROUPS_CREATED_AT_DATE, datetime.time(15, 0, 0), tzinfo=datetime.UTC
    )
    return Q(created_at__lte=created_at_as_dt)


def _update_follow_up_groups_created_in_bulk(apps, schema_editor):
    FollowUpGroup = apps.get_model("gps", "FollowUpGroup")
    groups = FollowUpGroup.objects.filter(_bulk_created_lookup()).exclude(created_in_bulk=True)

    count = 0
    start = time.perf_counter()
    while batch_groups := groups[:10000]:
        count += FollowUpGroup.objects.filter(pk__in=batch_groups.values_list("pk", flat=True)).update(
            created_in_bulk=True
        )
        logger.info(f"{count} groups migrated in {time.perf_counter() - start:.2f} sec")


def _update_groups_memberships_created_in_bulk(apps, schema_editor):
    FollowUpGroupMembership = apps.get_model("gps", "FollowUpGroupMembership")
    memberships = FollowUpGroupMembership.objects.filter(_bulk_created_lookup()).exclude(created_in_bulk=True)

    count = 0
    start = time.perf_counter()
    while batch_memberships := memberships[:10000]:
        count += FollowUpGroupMembership.objects.filter(pk__in=batch_memberships.values_list("pk", flat=True)).update(
            created_in_bulk=True
        )
        logger.info(f"{count} memberships migrated in {time.perf_counter() - start:.2f} sec")


class Migration(migrations.Migration):
    dependencies = [
        ("gps", "0002_followupgroup_created_in_bulk_and_more"),
    ]

    operations = [
        migrations.RunPython(_update_follow_up_groups_created_in_bulk, migrations.RunPython.noop, elidable=True),
        migrations.RunPython(_update_groups_memberships_created_in_bulk, migrations.RunPython.noop, elidable=True),
    ]
