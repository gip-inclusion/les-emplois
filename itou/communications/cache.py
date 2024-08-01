from datetime import date, datetime

from django.core.cache import cache

from itou.communications.models import AnnouncementCampaign


CACHE_ACTIVE_ANNOUNCEMENTS_KEY = "active-announcement-campaign"


def update_active_announcement_cache():
    campaign = AnnouncementCampaign.objects.filter(start_date=date.today().replace(day=1), live=True).prefetch_related(
        "items"
    )

    def get_cache_expiration():
        if not len(campaign):
            return None
        return (datetime.combine(campaign[0].end_date, datetime.min.time()) - datetime.now()).total_seconds()

    cache.set(CACHE_ACTIVE_ANNOUNCEMENTS_KEY, campaign, get_cache_expiration())
    return campaign


def get_cached_active_announcement():
    campaign = cache.get(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)
    if campaign is None:
        campaign = update_active_announcement_cache()
    return campaign.first()
