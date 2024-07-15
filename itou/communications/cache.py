from datetime import date, datetime

from django.core.cache import cache

from itou.communications.models import AnnouncementCampaign


CACHE_ACTIVE_ANNOUNCEMENTS_KEY = "active-announcement-campaign"
SENTINEL_ACTIVE_ANNOUNCEMENT = object()


def update_active_announcement_cache():
    campaign = (
        AnnouncementCampaign.objects.filter(start_date=date.today().replace(day=1), live=True)
        .prefetch_related("items")
        .first()
    )

    if campaign is None:
        cache.set(CACHE_ACTIVE_ANNOUNCEMENTS_KEY, None, None)
    else:
        cache_exp = (
            datetime.combine(campaign.end_date, datetime.min.time()) - datetime.now()
        ).total_seconds()  # seconds until the end_date, 00:00

        cache.set(CACHE_ACTIVE_ANNOUNCEMENTS_KEY, campaign, cache_exp)

    return campaign


def get_cached_active_announcement():
    campaign = cache.get(CACHE_ACTIVE_ANNOUNCEMENTS_KEY, SENTINEL_ACTIVE_ANNOUNCEMENT)
    if campaign == SENTINEL_ACTIVE_ANNOUNCEMENT:
        return update_active_announcement_cache()
    return campaign
