from datetime import datetime, timedelta

from django.core.cache import caches
from django.utils import timezone

from itou.communications.models import AnnouncementCampaign


CACHE_ACTIVE_ANNOUNCEMENTS_KEY = "active-announcement-campaign"
SENTINEL_ACTIVE_ANNOUNCEMENT = object()


def update_active_announcement_cache():
    campaign = (
        AnnouncementCampaign.objects.filter(start_date=timezone.localdate().replace(day=1), live=True)
        .prefetch_related("items")
        .first()
    )

    if campaign is None:
        caches["failsafe"].set(CACHE_ACTIVE_ANNOUNCEMENTS_KEY, None, None)
    else:
        cache_exp = (
            datetime.combine(campaign.end_date, datetime.min.time()) + timedelta(days=1) - datetime.now()
        ).total_seconds()  # seconds until the end_date, 00:00

        caches["failsafe"].set(CACHE_ACTIVE_ANNOUNCEMENTS_KEY, campaign, cache_exp)

    return campaign


def get_cached_active_announcement():
    active_announcement = caches["failsafe"].get(CACHE_ACTIVE_ANNOUNCEMENTS_KEY, SENTINEL_ACTIVE_ANNOUNCEMENT)
    if active_announcement is SENTINEL_ACTIVE_ANNOUNCEMENT:
        active_announcement = update_active_announcement_cache()
    return active_announcement
